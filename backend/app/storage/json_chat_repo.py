"""Chat storage in hidden JSON files (internal persistence, never shown to the user).

Layout:
    <data_dir>/users/<user_id>/chats/index.json      list of chat summaries
    <data_dir>/users/<user_id>/chats/<chat_id>.json  full chat with messages

Writes are atomic (temp file + os.replace) and serialised per user with an
asyncio lock, so a crash mid-write cannot leave a half-written file.
Only safe for a single backend process (one uvicorn worker).
"""

import asyncio
import json
import os
import re
import tempfile
import time
from pathlib import Path

from app.schemas import ChatCreate, ChatDetail, ChatSummary, DEFAULT_CHAT_TITLE, utc_now
from app.storage.base import ChatRepository

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _atomic_write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        # On Windows, antivirus/indexers can briefly lock the target file.
        for attempt in range(5):
            try:
                os.replace(tmp_name, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def _read_json(path: Path) -> object | None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


class JsonChatRepository(ChatRepository):
    def __init__(self, data_dir: Path) -> None:
        self._root = data_dir / "users"
        self._locks: dict[str, asyncio.Lock] = {}

    # ---------- helpers ----------

    def _lock(self, user_id: str) -> asyncio.Lock:
        return self._locks.setdefault(user_id, asyncio.Lock())

    def _chats_dir(self, user_id: str) -> Path:
        if not _SAFE_ID.match(user_id):
            raise ValueError("Invalid user id")
        return self._root / user_id / "chats"

    def _chat_path(self, user_id: str, chat_id: str) -> Path | None:
        if not _SAFE_ID.match(chat_id):
            return None
        return self._chats_dir(user_id) / f"{chat_id}.json"

    def _load_index(self, user_id: str) -> list[ChatSummary]:
        chats_dir = self._chats_dir(user_id)
        raw = _read_json(chats_dir / "index.json")
        if isinstance(raw, list):
            return [ChatSummary.model_validate(item) for item in raw]
        # Missing or corrupt index: rebuild it from the chat files.
        summaries: list[ChatSummary] = []
        if chats_dir.exists():
            for file in chats_dir.glob("*.json"):
                if file.name == "index.json":
                    continue
                data = _read_json(file)
                if isinstance(data, dict):
                    detail = ChatDetail.model_validate(data)
                    summaries.append(ChatSummary(**detail.model_dump(exclude={"messages"})))
        if summaries:
            self._save_index(user_id, summaries)
        return summaries

    def _save_index(self, user_id: str, summaries: list[ChatSummary]) -> None:
        _atomic_write_json(
            self._chats_dir(user_id) / "index.json",
            [s.model_dump(mode="json") for s in summaries],
        )

    # ---------- interface ----------

    async def list_chats(self, user_id: str) -> list[ChatSummary]:
        async with self._lock(user_id):
            summaries = await asyncio.to_thread(self._load_index, user_id)
        # Index is kept in "last touched" order; reversing first means that on a
        # timestamp tie (coarse clocks on Windows) the most recently touched chat wins.
        return sorted(reversed(summaries), key=lambda c: c.updated_at, reverse=True)

    async def create_chat(self, user_id: str, data: ChatCreate) -> ChatSummary:
        chat = ChatDetail(title=(data.title or DEFAULT_CHAT_TITLE).strip(), model=data.model)
        summary = ChatSummary(**chat.model_dump(exclude={"messages"}))

        def _write() -> None:
            path = self._chat_path(user_id, chat.id)
            assert path is not None
            # Load the index before writing the chat file: if the index has to be
            # rebuilt from the files, the new chat must not be picked up twice.
            index = self._load_index(user_id)
            _atomic_write_json(path, chat.model_dump(mode="json"))
            index.append(summary)
            self._save_index(user_id, index)

        async with self._lock(user_id):
            await asyncio.to_thread(_write)
        return summary

    async def get_chat(self, user_id: str, chat_id: str) -> ChatDetail | None:
        path = self._chat_path(user_id, chat_id)
        if path is None:
            return None
        async with self._lock(user_id):
            data = await asyncio.to_thread(_read_json, path)
        return ChatDetail.model_validate(data) if isinstance(data, dict) else None

    async def rename_chat(self, user_id: str, chat_id: str, title: str) -> ChatSummary | None:
        path = self._chat_path(user_id, chat_id)
        if path is None:
            return None

        def _write() -> ChatSummary | None:
            data = _read_json(path)
            if not isinstance(data, dict):
                return None
            chat = ChatDetail.model_validate(data)
            chat.title = title.strip()
            chat.updated_at = utc_now()
            _atomic_write_json(path, chat.model_dump(mode="json"))
            summary = ChatSummary(**chat.model_dump(exclude={"messages"}))
            index = [s for s in self._load_index(user_id) if s.id != chat_id]
            index.append(summary)
            self._save_index(user_id, index)
            return summary

        async with self._lock(user_id):
            return await asyncio.to_thread(_write)

    async def save_chat(self, user_id: str, chat: ChatDetail) -> ChatSummary | None:
        path = self._chat_path(user_id, chat.id)
        if path is None:
            return None

        def _write() -> ChatSummary | None:
            if not path.exists():
                return None  # deleted while a reply was streaming
            stored = chat.model_copy(deep=True)
            stored.updated_at = utc_now()
            _atomic_write_json(path, stored.model_dump(mode="json"))
            summary = ChatSummary(**stored.model_dump(exclude={"messages"}))
            index = [s for s in self._load_index(user_id) if s.id != chat.id]
            index.append(summary)
            self._save_index(user_id, index)
            return summary

        async with self._lock(user_id):
            return await asyncio.to_thread(_write)

    async def delete_chat(self, user_id: str, chat_id: str) -> bool:
        path = self._chat_path(user_id, chat_id)
        if path is None:
            return False

        def _delete() -> bool:
            index = self._load_index(user_id)
            remaining = [s for s in index if s.id != chat_id]
            existed = path.exists() or len(remaining) != len(index)
            if path.exists():
                path.unlink()
            if len(remaining) != len(index):
                self._save_index(user_id, remaining)
            return existed

        async with self._lock(user_id):
            return await asyncio.to_thread(_delete)
