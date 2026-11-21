"""Storage interfaces.

The rest of the app only depends on these interfaces, so the JSON / in-memory
implementations used now can later be swapped for SQLite, Qdrant, etc. by
adding a new class and changing STORAGE_BACKEND in .env.
"""

from abc import ABC, abstractmethod

from app.schemas import ChatCreate, ChatDetail, ChatSummary, User


class ChatRepository(ABC):
    @abstractmethod
    async def list_chats(self, user_id: str) -> list[ChatSummary]:
        """Return the user's chats, most recently updated first."""

    @abstractmethod
    async def create_chat(self, user_id: str, data: ChatCreate) -> ChatSummary: ...

    @abstractmethod
    async def get_chat(self, user_id: str, chat_id: str) -> ChatDetail | None: ...

    @abstractmethod
    async def rename_chat(self, user_id: str, chat_id: str, title: str) -> ChatSummary | None: ...

    @abstractmethod
    async def delete_chat(self, user_id: str, chat_id: str) -> bool: ...

    @abstractmethod
    async def save_chat(self, user_id: str, chat: ChatDetail) -> ChatSummary | None:
        """Overwrite an existing chat (messages, usage, title). None if it was deleted."""


class UserStore(ABC):
    @abstractmethod
    def authenticate(self, username: str, password: str) -> User | None: ...

    @abstractmethod
    def get_user(self, user_id: str) -> User | None: ...
