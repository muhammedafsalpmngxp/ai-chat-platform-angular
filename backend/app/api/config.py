"""Client configuration (limits the UI should know about)."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUser, SettingsDep
from app.services.extract import DOCUMENT_TYPES, IMAGE_TYPES, TEXT_EXTENSIONS

router = APIRouter(prefix="/config", tags=["config"])


class ClientConfig(BaseModel):
    max_upload_mb: int
    max_files_per_chat: int
    accept: str  # for <input type="file" accept="...">
    search_enabled: bool
    ask_data_enabled: bool


@router.get("", response_model=ClientConfig)
def client_config(_: CurrentUser, settings: SettingsDep) -> ClientConfig:
    extensions = sorted({*IMAGE_TYPES, *DOCUMENT_TYPES, *TEXT_EXTENSIONS})
    return ClientConfig(
        max_upload_mb=settings.max_upload_mb,
        max_files_per_chat=settings.max_files_per_chat,
        accept=",".join(extensions),
        search_enabled=bool(settings.tavily_api_key),
        ask_data_enabled=settings.ask_data_enabled,
    )
