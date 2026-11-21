"""FastAPI dependencies: settings, storage and the current user."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings
from app.core.models_catalog import ModelCatalog, load_catalog
from app.core.rate_limit import AttemptLimiter
from app.core.security import decode_access_token
from app.schemas import User
from app.services.chat_runner import ChatRunner
from app.storage import ChatRepository, UserStore
from app.storage.attachments import AttachmentStore

_bearer = HTTPBearer(auto_error=False)


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_chat_repo(request: Request) -> ChatRepository:
    return request.app.state.chat_repo


def get_user_store(request: Request) -> UserStore:
    return request.app.state.user_store


def get_chat_runner(request: Request) -> ChatRunner:
    return request.app.state.chat_runner


def get_attachment_store(request: Request) -> AttachmentStore:
    return request.app.state.attachments


def get_limiter(request: Request) -> AttemptLimiter:
    return request.app.state.password_limiter


def get_catalog(request: Request) -> ModelCatalog:
    return load_catalog(request.app.state.settings.models_config_path)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    users: Annotated[UserStore, Depends(get_user_store)],
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    user_id = decode_access_token(credentials.credentials, settings)
    user = users.get_user(user_id) if user_id else None
    if user is None:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ChatRepoDep = Annotated[ChatRepository, Depends(get_chat_repo)]
UserStoreDep = Annotated[UserStore, Depends(get_user_store)]
ChatRunnerDep = Annotated[ChatRunner, Depends(get_chat_runner)]
LimiterDep = Annotated[AttemptLimiter, Depends(get_limiter)]
CatalogDep = Annotated[ModelCatalog, Depends(get_catalog)]
AttachmentStoreDep = Annotated[AttachmentStore, Depends(get_attachment_store)]
