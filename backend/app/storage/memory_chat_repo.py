"""In-memory chat storage. Everything is lost when the process restarts."""

import asyncio

from app.schemas import ChatCreate, ChatDetail, ChatSummary, DEFAULT_CHAT_TITLE, utc_now
from app.storage.base import ChatRepository


class InMemoryChatRepository(ChatRepository):
    def __init__(self) -> None:
        self._chats: dict[str, dict[str, ChatDetail]] = {}
        self._lock = asyncio.Lock()

    async def list_chats(self, user_id: str) -> list[ChatSummary]:
        chats = self._chats.get(user_id, {}).values()
        summaries = [ChatSummary(**c.model_dump(exclude={"messages"})) for c in chats]
        # Dict is kept in "last touched" order; reversing first makes the most
        # recently touched chat win timestamp ties (coarse clocks on Windows).
        return sorted(reversed(summaries), key=lambda c: c.updated_at, reverse=True)

    async def create_chat(self, user_id: str, data: ChatCreate) -> ChatSummary:
        chat = ChatDetail(title=(data.title or DEFAULT_CHAT_TITLE).strip(), model=data.model)
        async with self._lock:
            self._chats.setdefault(user_id, {})[chat.id] = chat
        return ChatSummary(**chat.model_dump(exclude={"messages"}))

    async def get_chat(self, user_id: str, chat_id: str) -> ChatDetail | None:
        chat = self._chats.get(user_id, {}).get(chat_id)
        return chat.model_copy(deep=True) if chat else None

    async def rename_chat(self, user_id: str, chat_id: str, title: str) -> ChatSummary | None:
        async with self._lock:
            chats = self._chats.get(user_id, {})
            chat = chats.pop(chat_id, None)
            if chat is None:
                return None
            chats[chat_id] = chat  # move to the end ("last touched")
            chat.title = title.strip()
            chat.updated_at = utc_now()
            return ChatSummary(**chat.model_dump(exclude={"messages"}))

    async def save_chat(self, user_id: str, chat: ChatDetail) -> ChatSummary | None:
        async with self._lock:
            chats = self._chats.get(user_id, {})
            if chats.pop(chat.id, None) is None:
                return None
            stored = chat.model_copy(deep=True)
            stored.updated_at = utc_now()
            chats[chat.id] = stored  # move to the end ("last touched")
            return ChatSummary(**stored.model_dump(exclude={"messages"}))

    async def delete_chat(self, user_id: str, chat_id: str) -> bool:
        async with self._lock:
            return self._chats.get(user_id, {}).pop(chat_id, None) is not None
