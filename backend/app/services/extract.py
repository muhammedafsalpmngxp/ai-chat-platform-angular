"""Text extraction for uploaded documents (PDF, DOCX, plain-text formats)."""

import io
import logging

logger = logging.getLogger("chatbot.extract")

IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
DOCUMENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".xml", ".html", ".htm", ".log",
    ".yaml", ".yml", ".ini", ".toml", ".sql", ".py", ".js", ".ts", ".java", ".c", ".h",
    ".cpp", ".cs", ".go", ".rs", ".rb", ".php", ".sh", ".css", ".scss",
}

# Magic bytes so a renamed file can't pretend to be something else.
_SIGNATURES = {
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".gif": [b"GIF87a", b"GIF89a"],
    ".webp": [b"RIFF"],
    ".pdf": [b"%PDF"],
    ".docx": [b"PK\x03\x04"],
}


class UnsupportedFileError(ValueError):
    pass


def classify(extension: str, data: bytes) -> tuple[str, str]:
    """Return (kind, mime) for an allowed file, or raise UnsupportedFileError."""
    ext = extension.lower()
    if ext in _SIGNATURES and not any(data.startswith(sig) for sig in _SIGNATURES[ext]):
        raise UnsupportedFileError(f"The file content doesn't look like a {ext} file.")
    if ext == ".webp" and data[8:12] != b"WEBP":
        raise UnsupportedFileError("The file content doesn't look like a .webp file.")
    if ext in IMAGE_TYPES:
        return "image", IMAGE_TYPES[ext]
    if ext in DOCUMENT_TYPES:
        return "document", DOCUMENT_TYPES[ext]
    if ext in TEXT_EXTENSIONS:
        if b"\x00" in data[:4096]:
            raise UnsupportedFileError("This looks like a binary file, not text.")
        return "document", "text/plain"
    raise UnsupportedFileError(
        "Unsupported file type. Use images (PNG, JPG, WEBP, GIF), PDF, DOCX or text files."
    )


def extract_text(extension: str, data: bytes) -> str:
    ext = extension.lower()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            pages = []
            for number, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                if text:
                    pages.append(f"[Page {number}]\n{text}")
            return "\n\n".join(pages)
        if ext == ".docx":
            from docx import Document

            doc = Document(io.BytesIO(data))
            parts = [p.text for p in doc.paragraphs if p.text.strip()]
            for table in doc.tables:
                for row in table.rows:
                    parts.append(" | ".join(cell.text.strip() for cell in row.cells))
            return "\n".join(parts)
        for encoding in ("utf-8-sig", "utf-16"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("latin-1")
    except Exception:  # noqa: BLE001 - broken/encrypted files: keep the upload, no text
        logger.warning("Could not extract text from %s upload", ext, exc_info=True)
        return ""
