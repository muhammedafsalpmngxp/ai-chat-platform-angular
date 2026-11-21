from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import AttachmentStoreDep, ChatRepoDep, ChatRunnerDep, CurrentUser
from app.schemas import ChatCreate, ChatDetail, ChatSummary, ChatUpdate

router = APIRouter(prefix="/chats", tags=["chats"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")


@router.get("", response_model=list[ChatSummary])
async def list_chats(user: CurrentUser, repo: ChatRepoDep) -> list[ChatSummary]:
    return await repo.list_chats(user.id)


@router.post("", response_model=ChatSummary, status_code=status.HTTP_201_CREATED)
async def create_chat(body: ChatCreate, user: CurrentUser, repo: ChatRepoDep) -> ChatSummary:
    return await repo.create_chat(user.id, body)


@router.get("/{chat_id}", response_model=ChatDetail)
async def get_chat(chat_id: str, user: CurrentUser, repo: ChatRepoDep) -> ChatDetail:
    chat = await repo.get_chat(user.id, chat_id)
    if chat is None:
        raise _not_found()
    return chat


@router.patch("/{chat_id}", response_model=ChatSummary)
async def rename_chat(
    chat_id: str, body: ChatUpdate, user: CurrentUser, repo: ChatRepoDep
) -> ChatSummary:
    if not body.title.strip():
        raise HTTPException(status_code=422, detail="Title cannot be empty")
    chat = await repo.rename_chat(user.id, chat_id, body.title)
    if chat is None:
        raise _not_found()
    return chat


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat_id: str,
    user: CurrentUser,
    repo: ChatRepoDep,
    runner: ChatRunnerDep,
    attachments: AttachmentStoreDep,
) -> Response:
    if not await repo.delete_chat(user.id, chat_id):
        raise _not_found()
    await runner.forget(user.id, chat_id)
    await attachments.delete_chat(user.id, chat_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
