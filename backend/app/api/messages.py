"""Send a message and stream the reply as Server-Sent Events.

Events: start, token, replace, done, title, error  (data is JSON).
"""

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.deps import (
    AttachmentStoreDep,
    CatalogDep,
    ChatRepoDep,
    ChatRunnerDep,
    CurrentUser,
    SettingsDep,
)
from app.core.security import is_valid_premium_unlock
from app.schemas import SendMessageRequest
from app.services.chat_runner import ChatBusyError, Event

router = APIRouter(prefix="/chats", tags=["messages"])


async def _sse(events: AsyncIterator[Event]) -> AsyncIterator[str]:
    async for event in events:
        yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"


@router.post("/{chat_id}/messages")
async def send_message(
    chat_id: str,
    body: SendMessageRequest,
    user: CurrentUser,
    repo: ChatRepoDep,
    runner: ChatRunnerDep,
    settings: SettingsDep,
    catalog: CatalogDep,
    attachments_store: AttachmentStoreDep,
    premium_unlock: Annotated[str | None, Header(alias="X-Premium-Unlock")] = None,
) -> StreamingResponse:
    content = body.content.strip()
    if not content and not body.attachment_ids:
        raise HTTPException(status_code=422, detail="Message cannot be empty")

    chat = await repo.get_chat(user.id, chat_id)
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")

    attachments = []
    if body.attachment_ids:
        available = {a.id: a for a in await attachments_store.list(user.id, chat_id)}
        missing = [i for i in body.attachment_ids if i not in available]
        if missing:
            raise HTTPException(status_code=400, detail="One or more attached files were not found")
        attachments = [available[i] for i in dict.fromkeys(body.attachment_ids)]

    model_id = body.model or chat.model or catalog.default_id
    model = catalog.get(model_id)
    if model is None:
        raise HTTPException(status_code=400, detail=f"Unknown model '{model_id}'")
    if model.requires_reauth and not is_valid_premium_unlock(premium_unlock, user.id, settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{model.label} is a premium model. Re-enter your password to use it.",
            headers={"X-Error-Code": "reauth_required"},
        )

    try:
        events = runner.start_turn(
            user, chat, content, model.id, attachments=attachments, timezone=body.timezone, mode=body.mode
        )
    except ChatBusyError:
        raise HTTPException(status_code=409, detail="A reply is already being generated") from None

    return StreamingResponse(
        _sse(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
