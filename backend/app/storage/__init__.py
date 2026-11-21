"""Storage factory: picks implementations based on settings."""

from app.core.config import Settings
from app.storage.base import ChatRepository, UserStore
from app.storage.env_user_store import EnvUserStore
from app.storage.json_chat_repo import JsonChatRepository
from app.storage.memory_chat_repo import InMemoryChatRepository


def build_chat_repository(settings: Settings) -> ChatRepository:
    if settings.storage_backend == "memory":
        return InMemoryChatRepository()
    return JsonChatRepository(settings.data_dir)


def build_user_store(settings: Settings) -> UserStore:
    return EnvUserStore(settings)


__all__ = ["ChatRepository", "UserStore", "build_chat_repository", "build_user_store"]
