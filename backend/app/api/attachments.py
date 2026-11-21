"""Upload files to a chat (images and documents), list, download and remove them."""

from fastapi import APIRouter, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import AttachmentStoreDep, ChatRepoDep, CurrentUser
from app.schemas import AttachmentInfo
from app.services.extract import UnsupportedFileError
from app.storage.attachments import AttachmentLimitError

router = APIRouter(prefix="/chats/{chat_id}/attachments", tags=["attachments"])


async def _require_chat(repo, user_id: str, chat_id: str) -> None:
    if await repo.get_chat(user_id, chat_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")


@router.get("", response_model=list[AttachmentInfo])
async def list_attachments(
    chat_id: str, user: CurrentUser, repo: ChatRepoDep, store: AttachmentStoreDep
) -> list[AttachmentInfo]:
    await _require_chat(repo, user.id, chat_id)
    return await store.list(user.id, chat_id)


@router.post("", response_model=AttachmentInfo, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    chat_id: str, file: UploadFile, user: CurrentUser, repo: ChatRepoDep, store: AttachmentStoreDep
) -> AttachmentInfo:
    await _require_chat(repo, user.id, chat_id)
    data = await file.read(store.max_bytes + 1)  # never read more than the limit + 1 byte
    try:
        return await store.save(user.id, chat_id, file.filename or "file", data)
    except AttachmentLimitError as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from None
    except UnsupportedFileError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from None


@router.get("/{attachment_id}")
async def download_attachment(
    chat_id: str, attachment_id: str, user: CurrentUser, store: AttachmentStoreDep
) -> FileResponse:
    found = await store.get(user.id, chat_id, attachment_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    info, path = found
    return FileResponse(
        path,
        media_type=info.mime,
        filename=info.name,
        content_disposition_type="inline" if info.kind == "image" else "attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"},
    )


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    chat_id: str, attachment_id: str, user: CurrentUser, repo: ChatRepoDep, store: AttachmentStoreDep
) -> Response:
    chat = await repo.get_chat(user.id, chat_id)
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
    if any(a.id == attachment_id for m in chat.messages for a in m.attachments):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This file is already part of the chat")
    if not await store.delete(user.id, chat_id, attachment_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
