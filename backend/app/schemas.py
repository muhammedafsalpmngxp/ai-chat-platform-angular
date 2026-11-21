"""Pydantic models shared by the API and the storage layer."""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid4().hex


# ---------- Users / auth ----------


class User(BaseModel):
    id: str
    username: str
    display_name: str


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: User


# ---------- Chats ----------

DEFAULT_CHAT_TITLE = "New chat"


MessageStatus = Literal["complete", "stopped", "refused"]
AttachmentKind = Literal["image", "document"]


class AttachmentInfo(BaseModel):
    id: str
    name: str
    mime: str
    size: int
    kind: AttachmentKind
    # Documents: how much text could be read (0 = nothing, e.g. a scanned PDF).
    text_chars: int = 0
    truncated: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class Source(BaseModel):
    title: str
    url: str


class Message(BaseModel):
    id: str = Field(default_factory=new_id)
    role: Literal["user", "assistant", "system"]
    content: str
    status: MessageStatus = "complete"
    model: str | None = None
    attachments: list[AttachmentInfo] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    # Web answers: how well the sources agreed (from the evidence check).
    confidence: Literal["high", "medium", "low"] | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ChatSummary(BaseModel):
    id: str = Field(default_factory=new_id)
    title: str = DEFAULT_CHAT_TITLE
    model: str | None = None
    # Context window currently in use: last request's input + output tokens.
    token_count: int = 0
    # Running totals for the whole chat (used for cost in phase 3).
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cached_input_tokens: int = 0
    # Estimated spend for the chat, priced per turn with that turn's model.
    total_cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ChatDetail(ChatSummary):
    messages: list[Message] = Field(default_factory=list)


class ChatCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    model: str | None = None


class ChatUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class SendMessageRequest(BaseModel):
    content: str = Field(default="", max_length=32_000)
    model: str | None = None
    attachment_ids: list[str] = Field(default_factory=list, max_length=10)
    # IANA timezone from the browser, e.g. "Asia/Kolkata", so "now" is the user's now.
    timezone: str | None = Field(default=None, max_length=64)


# ---------- Models catalog ----------


class ModelInfo(BaseModel):
    id: str
    label: str
    tier: Literal["premium", "standard", "recommended", "low"]
    input_price: float
    output_price: float
    cached_input_price: float | None = None
    is_default: bool = False
    requires_reauth: bool = False
    warning: str | None = None
    # Price compared with the default model (e.g. 80.0 = about 80x GPT-6 Luna).
    relative_cost: float = 1.0


class ModelCatalogResponse(BaseModel):
    default_model: str
    prices_as_of: str | None
    premium_unlock_minutes: int
    models: list[ModelInfo]


# ---------- Premium re-authentication ----------


class ReauthRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class ReauthResponse(BaseModel):
    unlock_token: str
    expires_in: int
