"""Runs one chat turn through the LangGraph graph and streams events to the API.

Storage model:
- LangGraph's checkpointer (InMemorySaver) holds the live conversation per
  thread (thread_id = "<user_id>:<chat_id>").
- The JSON chat file is the durable copy. After every turn - finished, stopped
  or failed - the thread's messages are written back to it.
- After a backend restart the checkpointer is empty, so the first turn seeds
  the thread from the JSON file.

The graph runs in its own asyncio task, decoupled from the HTTP request. If the
client disconnects (Stop button), the task is cancelled, the partial answer is
added to the thread and saved, and the chat stays consistent.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    AnyMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from app.core.config import Settings
from app.core.models_catalog import ModelCatalog
from app.graph.builder import message_text
from app.graph.prompts import load_prompt, template
from app.graph.state import ChatContext, Usage
from app.schemas import (
    DEFAULT_CHAT_TITLE,
    AskDataResult,
    AttachmentInfo,
    ChatDetail,
    ChatSummary,
    Message,
    Source,
    User,
    new_id,
)
from app.services.ask_data import AskDataGateway
from app.services.llm import LLMFactory, MissingApiKeyError
from app.storage.attachments import attachment_refs

logger = logging.getLogger("chatbot.runner")

Event = dict[str, Any]
STREAMING_NODES = ("chitchat", "synthesizer")  # their LLM tokens go to the client
ANSWER_NODES = ("chitchat", "synthesizer", "web_search", "realtime", "refusal", "output_guard", "ask_data")
# Shown live in the UI while the graph runs (stream_mode="tasks").
STEP_LABELS = {
    "input_guard": "Safety check",
    "router": "Choosing how to answer",
    "chitchat": "Writing the answer",
    "web_search": "Searching the web",
    "evidence": "Checking facts across sources",
    "synthesizer": "Writing the answer",
    "realtime": "Checking live data",
    "ask_data": "Asking the company data",
    "refusal": "Preparing a reply",
    "output_guard": "Checking the answer",
}


class ChatBusyError(Exception):
    """A reply is already being generated for this chat."""


def _add_usage(total: Usage | None, extra: Usage | None) -> Usage | None:
    if not extra:
        return total
    if not total:
        return Usage(**extra)
    return Usage(**{k: total.get(k, 0) + extra.get(k, 0) for k in set(total) | set(extra)})


@dataclass(frozen=True)
class _Turn:
    content: str
    model: str
    attachments: list[AttachmentInfo]
    timezone: str
    mode: str = "auto"


# --------------------------------------------------------------- conversions


def to_langchain(message: Message) -> AnyMessage:
    if message.role == "user":
        meta = {"attachments": attachment_refs(message.attachments)} if message.attachments else {}
        return HumanMessage(content=message.content, id=message.id, response_metadata=meta)
    return AIMessage(
        content=message.content,
        id=message.id,
        response_metadata={
            "status": message.status,
            "model": message.model,
            "sources": [s.model_dump() for s in message.sources],
            "confidence": message.confidence,
            **({"ask_data": message.data.model_dump(mode="json")} if message.data else {}),
        },
    )


def from_langchain(message: AnyMessage, known: dict[str, Message]) -> Message | None:
    if isinstance(message, HumanMessage):
        role = "user"
    elif isinstance(message, AIMessage):
        role = "assistant"
    else:
        return None
    meta = message.response_metadata or {}
    previous = known.get(message.id or "")
    data = None
    if role == "assistant" and meta.get("ask_data"):
        try:
            data = AskDataResult.model_validate(meta["ask_data"])
        except ValueError:
            # Never let odd company data stop a chat from being saved: keep the text answer.
            logger.warning("Dropping Ask Data details that could not be saved", exc_info=True)
    result = Message(
        id=message.id or new_id(),
        role=role,
        content=message_text(message),
        status=meta.get("status", "complete") if role == "assistant" else "complete",
        model=meta.get("model") if role == "assistant" else None,
        attachments=[AttachmentInfo.model_validate(a) for a in meta.get("attachments") or []],
        sources=[Source.model_validate(s) for s in meta.get("sources") or []],
        confidence=meta.get("confidence") if meta.get("confidence") in ("high", "medium", "low") else None,
        data=data,
    )
    if previous is not None:
        result.created_at = previous.created_at
    return result


# -------------------------------------------------------------------- runner


class ChatRunner:
    def __init__(
        self,
        *,
        graph: CompiledStateGraph,
        checkpointer: BaseCheckpointSaver,
        repo,  # ChatRepository (imported lazily to avoid a cycle)
        llm_factory: LLMFactory,
        settings: Settings,
        catalog: ModelCatalog,
        ask_data: AskDataGateway | None = None,
    ) -> None:
        self._ask_data = ask_data
        self._catalog = catalog
        self._graph = graph
        self._checkpointer = checkpointer
        self._repo = repo
        self._llm_factory = llm_factory
        self._settings = settings
        self._busy: set[str] = set()
        self._tasks: set[asyncio.Task] = set()

    @staticmethod
    def thread_id(user_id: str, chat_id: str) -> str:
        return f"{user_id}:{chat_id}"

    def _config(self, user_id: str, chat_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": self.thread_id(user_id, chat_id)}}

    async def forget(self, user_id: str, chat_id: str) -> None:
        """Drop the in-memory thread (called when a chat is deleted)."""
        await self._checkpointer.adelete_thread(self.thread_id(user_id, chat_id))

    async def drain(self) -> None:
        """Wait for running turns to finish saving (used on shutdown and in tests)."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def start_turn(
        self,
        user: User,
        chat: ChatDetail,
        content: str,
        model: str,
        *,
        attachments: list[AttachmentInfo] | None = None,
        timezone: str | None = None,
        mode: str = "auto",
    ) -> AsyncIterator[Event]:
        """Start generating a reply now; returns the event stream for the response."""
        key = self.thread_id(user.id, chat.id)
        if key in self._busy:
            raise ChatBusyError
        self._busy.add(key)
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        turn = _Turn(
            content=content, model=model, attachments=attachments or [], timezone=timezone or "UTC", mode=mode
        )
        task = asyncio.create_task(self._run(user, chat, turn, queue, key))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return self._events(queue, task)

    @staticmethod
    async def _events(queue: asyncio.Queue, task: asyncio.Task) -> AsyncIterator[Event]:
        try:
            while (event := await queue.get()) is not None:
                yield event
        finally:
            if not task.done():
                task.cancel()  # client went away -> stop generating

    # ---------------------------------------------------------------- the turn

    async def _run(
        self,
        user: User,
        chat: ChatDetail,
        turn: "_Turn",
        queue: asyncio.Queue,
        key: str,
    ) -> None:
        emit = queue.put_nowait
        content, model = turn.content, turn.model
        config = self._config(user.id, chat.id)
        context = ChatContext(
            model=model,
            user_id=user.id,
            chat_id=chat.id,
            timezone=turn.timezone,
            mode=turn.mode,
            ask_data_connected=bool(self._ask_data and self._ask_data.is_connected(user.id)),
        )
        is_first_turn = not chat.messages
        human = HumanMessage(
            content=content,
            id=new_id(),
            response_metadata={"attachments": attachment_refs(turn.attachments)} if turn.attachments else {},
        )
        partial: list[str] = []
        usage: Usage | None = None
        router_usage: Usage | None = None
        answered = False

        try:
            snapshot = await self._graph.aget_state(config)
            if snapshot.values.get("messages"):
                inputs: list[AnyMessage] = [human]
            else:  # cold thread (new chat or backend restarted): seed from JSON
                inputs = [to_langchain(m) for m in chat.messages] + [human]

            emit({"event": "start", "data": {
                "user_message": from_langchain(human, {}).model_dump(mode="json"),
                "model": model,
            }})

            async for mode, data in self._graph.astream(
                {"messages": inputs},
                config,
                context=context,
                stream_mode=["messages", "updates", "tasks", "custom"],
            ):
                if mode == "tasks":
                    node = data.get("name")
                    if node in STEP_LABELS:
                        done = "result" in data or "error" in data
                        emit({"event": "step", "data": {
                            "node": node,
                            "label": STEP_LABELS[node],
                            "status": "done" if done else "running",
                        }})
                    continue
                if mode == "custom":
                    if isinstance(data, dict) and isinstance(data.get("answer_delta"), str):
                        # Text pieces from a non-LLM node (the company Ask Data agent).
                        partial.append(data["answer_delta"])
                        emit({"event": "token", "data": {"text": data["answer_delta"]}})
                    elif isinstance(data, dict) and data.get("node") in STEP_LABELS:
                        emit({"event": "step", "data": {
                            "node": data["node"],
                            "label": STEP_LABELS[data["node"]],
                            "status": "running",
                            "detail": str(data.get("detail", ""))[:120],
                        }})
                    continue
                if mode == "messages":
                    chunk, meta = data
                    if meta.get("langgraph_node") in STREAMING_NODES and isinstance(chunk, AIMessageChunk):
                        text = str(chunk.text)
                        if text:
                            partial.append(text)
                            emit({"event": "token", "data": {"text": text}})
                    continue
                for node, update in (data or {}).items():
                    if not update:
                        continue
                    if node == "router":
                        router_usage = _add_usage(router_usage, update.get("router_usage"))
                    if node == "evidence":
                        router_usage = _add_usage(router_usage, update.get("evidence_usage"))
                    if node in STREAMING_NODES:
                        usage = update.get("usage")
                    if node in ANSWER_NODES and update.get("messages"):
                        reply_msg = update["messages"][-1]
                        status = reply_msg.response_metadata.get("status", "complete")
                        # Fixed replies (no tokens), guard replacements and cleaned-up text
                        # (e.g. citation markers removed) overwrite the streamed bubble.
                        if status == "refused" or not partial or message_text(reply_msg) != "".join(partial):
                            emit({"event": "replace", "data": {
                                "text": message_text(reply_msg),
                                "status": status,
                            }})

            summary, reply = await self._save(user, chat, model, usage, router_usage)
            answered = True
            emit({"event": "done", "data": {
                "message": reply.model_dump(mode="json") if reply else None,
                "chat": summary.model_dump(mode="json") if summary else None,
            }})

            if summary and is_first_turn and chat.title == DEFAULT_CHAT_TITLE:
                title_source = content or ", ".join(a.name for a in turn.attachments)
                titled = await self._set_title(user, chat, title_source, reply)
                if titled:
                    emit({"event": "title", "data": {"chat": titled.model_dump(mode="json")}})

        except asyncio.CancelledError:
            if not answered:
                await self._save_stopped(user, chat, model, config, partial, usage, router_usage)
            raise
        except MissingApiKeyError:
            await self._save_quietly(user, chat, model, usage, router_usage)
            emit({"event": "error", "data": {"detail": template("missing_api_key")}})
        except Exception as exc:  # noqa: BLE001 - report any model/API failure to the client
            logger.exception("Chat turn failed")
            await self._save_quietly(user, chat, model, usage, router_usage)
            detail = template("model_error")
            if self._settings.environment == "development":
                detail += f"\n\n({type(exc).__name__}: {exc})"
            emit({"event": "error", "data": {"detail": detail}})
        finally:
            self._busy.discard(key)
            emit(None)

    async def _save_quietly(self, user, chat, model, usage, router_usage) -> None:
        """Best-effort save on the error path: a second failure must not hide the first."""
        try:
            await self._save(user, chat, model, usage, router_usage)
        except Exception:  # noqa: BLE001
            logger.exception("Could not save the chat after a failed turn")

    async def _save_stopped(self, user, chat, model, config, partial, usage, router_usage) -> None:
        try:
            if partial:
                stopped = AIMessage(
                    content="".join(partial),
                    response_metadata={"status": "stopped", "model": model},
                )
                # Record the partial answer as if the graph had finished.
                await self._graph.aupdate_state(config, {"messages": [stopped]}, as_node="output_guard")
            await self._save(user, chat, model, usage, router_usage)
        except Exception:  # noqa: BLE001
            logger.exception("Could not save a stopped reply")

    async def _save(
        self,
        user: User,
        chat: ChatDetail,
        model: str,
        usage: Usage | None,
        router_usage: Usage | None = None,
    ) -> tuple[ChatSummary | None, Message | None]:
        """Copy the thread's messages (and this turn's usage) into the JSON chat."""
        state = await self._graph.aget_state(self._config(user.id, chat.id))
        known = {m.id: m for m in chat.messages}
        messages = [
            converted
            for m in state.values.get("messages", [])
            if (converted := from_langchain(m, known)) is not None
        ]
        current = await self._repo.get_chat(user.id, chat.id)
        if current is not None:
            chat.title = current.title  # keep a rename made while the reply streamed
        chat.messages = messages
        chat.model = model
        if usage:
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            cached = usage.get("cached_input_tokens", 0)
            chat.token_count = input_tokens + output_tokens
            chat.total_input_tokens += input_tokens
            chat.total_output_tokens += output_tokens
            chat.total_cached_input_tokens += cached
            # Priced with this turn's model, so switching models mid-chat stays accurate.
            chat.total_cost_usd = round(
                chat.total_cost_usd
                + self._catalog.cost_usd(model, input_tokens, output_tokens, cached),
                8,
            )
        if router_usage:
            # The router's small model call costs money too (not part of the context window).
            chat.total_cost_usd = round(
                chat.total_cost_usd
                + self._catalog.cost_usd(
                    self._settings.utility_model,
                    router_usage.get("input_tokens", 0),
                    router_usage.get("output_tokens", 0),
                    router_usage.get("cached_input_tokens", 0),
                ),
                8,
            )
        summary = await self._repo.save_chat(user.id, chat)
        if summary is None:  # chat was deleted meanwhile
            await self.forget(user.id, chat.id)
        reply = next((m for m in reversed(messages) if m.role == "assistant"), None)
        return summary, reply

    async def _set_title(
        self, user: User, chat: ChatDetail, question: str, reply: Message | None
    ) -> ChatSummary | None:
        title = ""
        # Ask Data replies contain company data: never send them to OpenAI for a title.
        if reply and reply.status == "complete" and reply.data is None and reply.model != "ask-data":
            try:
                llm = self._llm_factory(self._settings.utility_model)
                result = await llm.ainvoke([
                    SystemMessage(content=load_prompt("chat_title")),
                    HumanMessage(content=f"User: {question[:1000]}\n\nAssistant: {reply.content[:1000]}"),
                ])
                title = message_text(result)
            except Exception:  # noqa: BLE001 - a title is nice-to-have
                logger.warning("Title generation failed", exc_info=True)
        title = title.strip().strip("\"'“”").rstrip(".").strip()
        if not title:
            words = question.split()
            title = " ".join(words[:6]) + ("…" if len(words) > 6 else "")
        return await self._repo.rename_chat(user.id, chat.id, title[:80])
