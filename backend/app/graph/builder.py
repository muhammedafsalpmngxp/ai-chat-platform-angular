"""The chat graph.

    START -> input_guard --explicit--> refusal -> END
                        \--safe--> router --chitchat----> chitchat ---------------------------> output_guard -> END
                                          --web_search--> web_search -> evidence -> synthesizer -/
                                          --realtime----> realtime -> END

web_search  researches (1-2 queries in parallel, filtered and de-duplicated),
evidence    compares every candidate across the results with the utility model,
synthesizer writes the final answer from the checked notes (no citation markers).

Phase 5 adds a memory retriever before chitchat / web_search; the node
functions and state keep the same shape.
"""

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Literal

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    message_chunk_to_message,
)
from langchain_core.messages.utils import count_tokens_approximately, trim_messages
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import StreamWriter

from app.graph.prompts import load_prompt, local_now, system_prompt, template
from app.graph.rules import is_datetime_question, is_realtime, is_trivial, likely_needs_search
from app.graph.state import ChatContext, ChatState, Intent, Usage
from app.services.llm import LLMFactory, Moderator
from app.services.search import Searcher, SearchResult, is_blocked_url, is_low_trust_url
from app.storage.attachments import LoadedAttachment

logger = logging.getLogger("chatbot.graph")

AttachmentLoader = Callable[[str, str, list[str]], Awaitable[list[LoadedAttachment]]]

# "[1]", "[2][3]", "[1, 4]", "[2-3]" - but not markdown links "[1](...)".
_CITATION = re.compile(r"[ \t]?\[\d{1,2}(?:\s*[,–-]\s*\d{1,2})*\](?!\()")


def strip_citations(text: str) -> str:
    """Remove inline citation markers; sources are shown separately in the UI."""
    cleaned = _CITATION.sub("", text)
    return re.sub(r"[ \t]+([.,;:!?])", r"\1", cleaned)


def message_text(message: BaseMessage) -> str:
    return str(message.text)


def attachment_refs(message: BaseMessage) -> list[dict]:
    return list((message.response_metadata or {}).get("attachments") or [])


def _last(messages: list[AnyMessage], kind: type[BaseMessage]) -> BaseMessage | None:
    return next((m for m in reversed(messages) if isinstance(m, kind)), None)


def _usage_from(message: AIMessage) -> Usage:
    meta = message.usage_metadata or {}
    details = meta.get("input_token_details") or {}
    return Usage(
        input_tokens=int(meta.get("input_tokens", 0)),
        output_tokens=int(meta.get("output_tokens", 0)),
        cached_input_tokens=int(details.get("cache_read", 0) or 0),
    )


def _expand_human(message: HumanMessage, loaded: list[LoadedAttachment]) -> HumanMessage:
    """Turn stored attachment references into content the model can read/see."""
    text = message_text(message)
    docs, images = [], []
    for item in loaded:
        if item.info.kind == "image":
            images.append({"type": "image_url", "image_url": {"url": item.data_url}})
            docs.append(f'<attachment name="{item.info.name}" type="image" />')
        else:
            body = item.text or "(No readable text - the file may be scanned or empty.)"
            note = "\n(Text was cut off because the file is long.)" if item.info.truncated else ""
            docs.append(f'<attachment name="{item.info.name}">\n{body}{note}\n</attachment>')
    full_text = "\n\n".join([*docs, text]) if docs else text
    if not images:
        return HumanMessage(content=full_text, id=message.id)
    return HumanMessage(content=[{"type": "text", "text": full_text}, *images], id=message.id)


def _format_results(results: list[dict]) -> str:
    lines = ["<search_results>"]
    for number, r in enumerate(results, start=1):
        date = f" ({r['published']})" if r.get("published") else ""
        lines.append(f"[{number}] {r['title']}{date} - {r['url']}\n    {r['content']}")
    lines.append("</search_results>")
    return "\n".join(lines)


def _format_evidence(evidence: dict) -> str:
    if not evidence:
        return ""
    lines = ["<verified_notes>", f"Confidence: {evidence.get('confidence', 'unknown')}"]
    if evidence.get("answer"):
        lines.append(f"Best-supported answer: {evidence['answer']}")
    candidates = evidence.get("candidates") or []
    if candidates:
        lines.append("Candidates compared:")
        for c in candidates[:15]:
            basis = f" ({c.get('basis')})" if c.get("basis") else ""
            date = f", {c.get('date')}" if c.get("date") else ""
            sources = ", ".join(str(s) for s in c.get("sources") or [])
            lines.append(f"- {c.get('name')}: {c.get('value')}{basis} [sources {sources}{date}]")
    for key, label in (("conflicts", "Conflicts"), ("out_of_scope", "Out of scope"), ("missing", "Not confirmed")):
        if evidence.get(key):
            lines.append(f"{label}: {evidence[key]}")
    lines.append("</verified_notes>")
    return "\n".join(lines)


def _json_object(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _parse_router_json(text: str) -> tuple[Intent | None, list[str]]:
    data = _json_object(text)
    if not data or data.get("intent") not in ("chitchat", "web_search", "realtime"):
        return None, []
    queries = data.get("search_queries")
    if not isinstance(queries, list):
        queries = [data.get("search_query")]  # older single-query format
    return data["intent"], [str(q).strip() for q in queries if q and str(q).strip()]


def build_chat_graph(
    *,
    llm_factory: LLMFactory,
    moderator: Moderator,
    searcher: Searcher | None = None,
    attachment_loader: AttachmentLoader | None = None,
    assistant_name: str = "AI Chatbot",
    utility_model: str = "gpt-6-luna",
    router_use_llm: bool = True,
    history_max_tokens: int = 60_000,
    search_max_queries: int = 2,
    search_max_sources: int = 8,
    search_verify: bool = True,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    # ---------------------------------------------------------------- helpers

    async def prompt_history(messages: list[AnyMessage], ctx: ChatContext) -> list[BaseMessage]:
        history = trim_messages(
            messages,
            max_tokens=history_max_tokens,
            token_counter=count_tokens_approximately,
            strategy="last",
            start_on="human",
            include_system=False,
        )
        result: list[BaseMessage] = []
        for message in history:
            refs = attachment_refs(message) if isinstance(message, HumanMessage) else []
            if refs and attachment_loader is not None:
                loaded = await attachment_loader(ctx.user_id, ctx.chat_id, [r["id"] for r in refs])
                result.append(_expand_human(message, loaded))
            else:
                result.append(message)
        return result

    async def stream_answer(prompt: list[BaseMessage], config: RunnableConfig, model: str) -> AIMessage:
        llm = llm_factory(model)
        # astream so tokens reach stream_mode="messages" as they are generated.
        full = None
        async for chunk in llm.astream(prompt, config):
            full = chunk if full is None else full + chunk
        reply = message_chunk_to_message(full) if full is not None else AIMessage(content="")
        reply.response_metadata = {**(reply.response_metadata or {}), "status": "complete", "model": model}
        return reply

    def latest_question(state: ChatState) -> str:
        human = _last(state["messages"], HumanMessage)
        return message_text(human) if human else ""

    # ------------------------------------------------------------------ nodes

    async def input_guard(state: ChatState) -> dict:
        text = latest_question(state)
        if is_trivial(text):
            return {"safety": "safe"}
        explicit = await moderator.is_explicit(text)
        return {"safety": "explicit" if explicit else "safe"}

    def refusal(state: ChatState) -> dict:
        reply = AIMessage(content=template("explicit_refusal"), response_metadata={"status": "refused"})
        return {"messages": [reply], "usage": Usage()}

    async def router(state: ChatState, config: RunnableConfig, runtime: Runtime[ChatContext]) -> dict:
        human = _last(state["messages"], HumanMessage)
        text = latest_question(state)
        quiet = {"search_queries": [], "router_usage": Usage()}
        if is_trivial(text) or is_datetime_question(text) or (human is not None and attachment_refs(human)):
            return {"intent": "chitchat", **quiet}
        if is_realtime(text):
            return {"intent": "realtime", **quiet}

        fallback: Intent = "web_search" if likely_needs_search(text) else "chitchat"
        if not router_use_llm:
            return {"intent": fallback, "search_queries": [text], "router_usage": Usage()}

        earlier = [m for m in state["messages"] if m is not human][-6:]
        transcript = "\n".join(
            f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {message_text(m)[:400]}"
            for m in earlier
        )
        today = local_now(runtime.context.timezone).date().isoformat()
        prompt = [
            SystemMessage(content=load_prompt("router").format(today=today)),
            HumanMessage(content=f"Earlier messages:\n{transcript or '(none)'}\n\nLatest message:\n{text}"),
        ]
        try:
            llm = llm_factory(utility_model).bind(response_format={"type": "json_object"})
            result = await llm.ainvoke(prompt, config)
            intent, queries = _parse_router_json(message_text(result))
            usage = _usage_from(result)
        except Exception:  # noqa: BLE001 - routing must never break the chat
            logger.warning("LLM router failed; using rules", exc_info=True)
            intent, queries, usage = None, [], Usage()
        return {
            "intent": intent or fallback,
            "search_queries": (queries or [text])[:search_max_queries],
            "router_usage": usage,
        }

    async def chitchat(state: ChatState, config: RunnableConfig, runtime: Runtime[ChatContext]) -> dict:
        ctx = runtime.context
        prompt = [
            SystemMessage(content=system_prompt(assistant_name, local_now(ctx.timezone))),
            *await prompt_history(state["messages"], ctx),
        ]
        reply = await stream_answer(prompt, config, ctx.model)
        return {"messages": [reply], "usage": _usage_from(reply)}

    async def web_search(state: ChatState, writer: StreamWriter) -> dict:
        """Research: run the queries in parallel, then filter, de-duplicate and cap."""
        queries = state.get("search_queries") or [latest_question(state)]
        writer({"node": "web_search", "detail": "Searching: " + " | ".join(f'"{q[:60]}"' for q in queries)})
        empty = {"search_results": [], "evidence": {}, "search_refused": False}

        if searcher is None:
            writer({"node": "web_search", "detail": "Web search unavailable"})
            return {**empty, "search_note": template("search_unavailable")}

        outcomes = await asyncio.gather(*(searcher.search(q) for q in queries), return_exceptions=True)
        raw: list[SearchResult] = []
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                logger.warning("A web search query failed: %s", outcome)
            else:
                raw.extend(outcome)
        if all(isinstance(o, BaseException) for o in outcomes):
            writer({"node": "web_search", "detail": "Web search failed"})
            return {**empty, "search_note": template("search_unavailable")}

        seen: set[str] = set()
        unique: list[SearchResult] = []
        for r in raw:
            key = r.url.split("#")[0].rstrip("/").lower()
            if key not in seen:
                seen.add(key)
                unique.append(r)
        found_any = bool(unique)
        results = [r for r in unique if not is_blocked_url(r.url) and not is_low_trust_url(r.url)]
        if results:
            writer({"node": "web_search", "detail": f"Found {len(results)} pages, safety-checking them"})
            flags = await moderator.explicit_flags([f"{r.title}\n{r.content}" for r in results])
            explicit = [r for r, flagged in zip(results, flags) if flagged]
            results = [r for r, flagged in zip(results, flags) if not flagged][:search_max_sources]
            if found_any and not results and explicit:
                # Everything usable that the web returned was explicit: show nothing.
                reply = AIMessage(content=template("explicit_refusal"), response_metadata={"status": "refused"})
                return {**empty, "messages": [reply], "usage": Usage(), "search_refused": True, "search_note": ""}
        if not results:
            writer({"node": "web_search", "detail": "No usable results"})
            return {**empty, "search_note": template("search_no_results")}

        writer({"node": "web_search", "detail": f"Collected {len(results)} sources"})
        return {
            **empty,
            "search_results": [
                {"title": r.title, "url": r.url, "content": r.content, "published": r.published} for r in results
            ],
            "search_note": "",
        }

    async def evidence(
        state: ChatState, config: RunnableConfig, runtime: Runtime[ChatContext], writer: StreamWriter
    ) -> dict:
        """Compare what every source says before anything is written."""
        results = state.get("search_results") or []
        if not results or not search_verify:
            return {"evidence": {}, "evidence_usage": Usage()}
        writer({"node": "evidence", "detail": f"Comparing {len(results)} sources"})
        today = local_now(runtime.context.timezone).date().isoformat()
        prompt = [
            SystemMessage(content=load_prompt("evidence").format(today=today)),
            HumanMessage(content=f"Question: {latest_question(state)}\n\n{_format_results(results)}"),
        ]
        try:
            llm = llm_factory(utility_model).bind(response_format={"type": "json_object"})
            result = await llm.ainvoke(prompt, config)
            notes = _json_object(message_text(result)) or {}
            usage = _usage_from(result)
        except Exception:  # noqa: BLE001 - the writer can still use the raw results
            logger.warning("Evidence check failed; answering from raw results", exc_info=True)
            notes, usage = {}, Usage()
        confidence = notes.get("confidence")
        if confidence not in ("high", "medium", "low"):
            notes.pop("confidence", None)
        if notes:
            writer({"node": "evidence", "detail": f"Confidence: {notes.get('confidence', 'unknown')}"})
        return {"evidence": notes, "evidence_usage": usage}

    async def synthesizer(state: ChatState, config: RunnableConfig, runtime: Runtime[ChatContext]) -> dict:
        """Write the final web answer from the checked notes (no citation markers)."""
        ctx = runtime.context
        results = state.get("search_results") or []
        notes = state.get("evidence") or {}
        if results:
            context_text = "\n\n".join(filter(None, [_format_evidence(notes), _format_results(results)]))
        else:
            context_text = state.get("search_note") or template("search_no_results")

        history = await prompt_history(state["messages"], ctx)
        # Notes and results go right before the latest question; they are not saved in the thread.
        prompt = [
            SystemMessage(content=system_prompt(assistant_name, local_now(ctx.timezone))),
            SystemMessage(content=load_prompt("synthesizer")),
            *history[:-1],
            SystemMessage(content=context_text),
            *history[-1:],
        ]
        reply = await stream_answer(prompt, config, ctx.model)
        reply.content = strip_citations(message_text(reply))
        reply.response_metadata["sources"] = [{"title": r["title"], "url": r["url"]} for r in results]
        if results and notes.get("confidence"):
            reply.response_metadata["confidence"] = notes["confidence"]
        return {"messages": [reply], "usage": _usage_from(reply)}

    def realtime(state: ChatState) -> dict:
        reply = AIMessage(content=template("realtime_unknown"), response_metadata={"status": "complete"})
        return {"messages": [reply], "usage": Usage()}

    async def output_guard(state: ChatState) -> dict | None:
        reply = _last(state["messages"], AIMessage)
        if reply is None or reply.response_metadata.get("status") == "refused":
            return None
        if not await moderator.is_explicit(message_text(reply)):
            return None
        # Same id => add_messages replaces the streamed answer instead of appending.
        replacement = AIMessage(
            id=reply.id,
            content=template("explicit_refusal"),
            response_metadata={**reply.response_metadata, "status": "refused", "sources": [], "confidence": None},
            usage_metadata=reply.usage_metadata,
        )
        return {"messages": [replacement], "safety": "explicit"}

    # ------------------------------------------------------------------ edges

    def after_input_guard(state: ChatState) -> Literal["refusal", "router"]:
        return "refusal" if state.get("safety") == "explicit" else "router"

    def after_router(state: ChatState) -> Literal["chitchat", "web_search", "realtime"]:
        return state.get("intent", "chitchat")

    def after_web_search(state: ChatState) -> Literal["evidence", "synthesizer", "__end__"]:
        if state.get("search_refused"):
            return END  # every result was explicit: the refusal is already the reply
        return "evidence" if state.get("search_results") else "synthesizer"

    graph = StateGraph(ChatState, context_schema=ChatContext)
    graph.add_node("input_guard", input_guard)
    graph.add_node("refusal", refusal)
    graph.add_node("router", router)
    graph.add_node("chitchat", chitchat)
    graph.add_node("web_search", web_search)
    graph.add_node("evidence", evidence)
    graph.add_node("synthesizer", synthesizer)
    graph.add_node("realtime", realtime)
    graph.add_node("output_guard", output_guard)

    graph.add_edge(START, "input_guard")
    graph.add_conditional_edges("input_guard", after_input_guard)
    graph.add_conditional_edges("router", after_router)
    graph.add_conditional_edges("web_search", after_web_search)
    graph.add_edge("evidence", "synthesizer")
    graph.add_edge("chitchat", "output_guard")
    graph.add_edge("synthesizer", "output_guard")
    graph.add_edge("output_guard", END)
    graph.add_edge("refusal", END)
    graph.add_edge("realtime", END)

    return graph.compile(checkpointer=checkpointer, name="chat")
