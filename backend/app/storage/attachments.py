"""Uploaded files, stored next to the chat data (git-ignored, never public).

Layout: <data_dir>/users/<user_id>/uploads/<chat_id>/
    <id>.bin   original bytes
    <id>.json  AttachmentInfo
    <id>.txt   extracted text (documents)
"""

from __future__ import annotations  # the `list` method below would shadow list[...] hints

import asyncio
import base64
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.schemas import AttachmentInfo, new_id
from app.services.extract import classify, extract_text

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class AttachmentLimitError(ValueError):
    pass


@dataclass(frozen=True)
class LoadedAttachment:
    info: AttachmentInfo
    text: str = ""  # documents
    data_url: str = ""  # images


def _safe_name(name: str) -> str:
    name = Path(name or "file").name.strip() or "file"
    return re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "_", name)[:120]


class AttachmentStore:
    def __init__(self, data_dir: Path, max_bytes: int, max_files: int, max_chars: int) -> None:
        self._root = data_dir / "users"
        self.max_bytes = max_bytes
        self.max_files = max_files
        self._max_chars = max_chars
        self._lock = asyncio.Lock()

    def _dir(self, user_id: str, chat_id: str) -> Path:
        if not (_SAFE_ID.match(user_id) and _SAFE_ID.match(chat_id)):
            raise ValueError("Invalid id")
        return self._root / user_id / "uploads" / chat_id

    def _list_sync(self, user_id: str, chat_id: str) -> list[AttachmentInfo]:
        folder = self._dir(user_id, chat_id)
        if not folder.exists():
            return []
        infos = [AttachmentInfo.model_validate_json(p.read_text(encoding="utf-8")) for p in folder.glob("*.json")]
        return sorted(infos, key=lambda a: a.created_at)

    async def list(self, user_id: str, chat_id: str) -> list[AttachmentInfo]:
        return await asyncio.to_thread(self._list_sync, user_id, chat_id)

    async def save(self, user_id: str, chat_id: str, filename: str, data: bytes) -> AttachmentInfo:
        if len(data) > self.max_bytes:
            raise AttachmentLimitError(f"File is larger than {self.max_bytes // (1024 * 1024)} MB.")
        if not data:
            raise AttachmentLimitError("The file is empty.")
        name = _safe_name(filename)
        extension = Path(name).suffix
        kind, mime = classify(extension, data)  # raises UnsupportedFileError

        def _write() -> AttachmentInfo:
            folder = self._dir(user_id, chat_id)
            if len(self._list_sync(user_id, chat_id)) >= self.max_files:
                raise AttachmentLimitError(f"A chat can have at most {self.max_files} files.")
            folder.mkdir(parents=True, exist_ok=True)
            info = AttachmentInfo(id=new_id(), name=name, mime=mime, size=len(data), kind=kind)
            if kind == "document":
                text = extract_text(extension, data)
                info.truncated = len(text) > self._max_chars
                text = text[: self._max_chars]
                info.text_chars = len(text)
                (folder / f"{info.id}.txt").write_text(text, encoding="utf-8")
            (folder / f"{info.id}.bin").write_bytes(data)
            (folder / f"{info.id}.json").write_text(info.model_dump_json(), encoding="utf-8")
            return info

        async with self._lock:
            return await asyncio.to_thread(_write)

    async def get(self, user_id: str, chat_id: str, attachment_id: str) -> tuple[AttachmentInfo, Path] | None:
        if not _SAFE_ID.match(attachment_id):
            return None
        folder = self._dir(user_id, chat_id)
        meta = folder / f"{attachment_id}.json"
        if not meta.exists():
            return None
        info = AttachmentInfo.model_validate_json(meta.read_text(encoding="utf-8"))
        return info, folder / f"{attachment_id}.bin"

    async def delete(self, user_id: str, chat_id: str, attachment_id: str) -> bool:
        if not _SAFE_ID.match(attachment_id):
            return False
        folder = self._dir(user_id, chat_id)

        def _delete() -> bool:
            found = False
            for suffix in (".json", ".bin", ".txt"):
                path = folder / f"{attachment_id}{suffix}"
                if path.exists():
                    path.unlink()
                    found = True
            return found

        async with self._lock:
            return await asyncio.to_thread(_delete)

    async def delete_chat(self, user_id: str, chat_id: str) -> None:
        folder = self._dir(user_id, chat_id)
        await asyncio.to_thread(shutil.rmtree, folder, True)

    async def load(self, user_id: str, chat_id: str, ids: list[str]) -> list[LoadedAttachment]:
        """Read attachments for the prompt (missing ones are skipped)."""

        def _load() -> list[LoadedAttachment]:
            folder = self._dir(user_id, chat_id)
            loaded = []
            for attachment_id in ids:
                if not _SAFE_ID.match(attachment_id):
                    continue
                meta = folder / f"{attachment_id}.json"
                if not meta.exists():
                    continue
                info = AttachmentInfo.model_validate_json(meta.read_text(encoding="utf-8"))
                if info.kind == "image":
                    raw = (folder / f"{attachment_id}.bin").read_bytes()
                    url = f"data:{info.mime};base64,{base64.b64encode(raw).decode('ascii')}"
                    loaded.append(LoadedAttachment(info=info, data_url=url))
                else:
                    text_path = folder / f"{attachment_id}.txt"
                    text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""
                    loaded.append(LoadedAttachment(info=info, text=text))
            return loaded

        return await asyncio.to_thread(_load)


def attachment_refs(infos: list[AttachmentInfo]) -> list[dict]:
    """Compact form stored on the LangChain message (response_metadata)."""
    return [json.loads(i.model_dump_json()) for i in infos]
