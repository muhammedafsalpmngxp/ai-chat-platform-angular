"""LangGraph state and per-run context for the chat graph."""

from dataclasses import dataclass
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

Intent = Literal["chitchat", "web_search", "realtime", "ask_data"]
Safety = Literal["safe", "explicit"]


class Usage(TypedDict, total=False):
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int


class ChatState(TypedDict, total=False):
    """Shared state that flows through every node.

    `messages` is the conversation (saved by the checkpointer per thread).
    The other keys describe the current turn only.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    intent: Intent
    search_queries: list[str]
    search_results: list[dict]  # title, url, content, published (this turn only)
    search_note: str  # e.g. "search unavailable" instructions for the writer
    search_refused: bool  # every result was explicit -> the turn ends with a refusal
    evidence: dict  # output of the evidence check (candidates, answer, confidence...)
    safety: Safety
    usage: Usage  # the answering model's tokens (context meter + cost)
    router_usage: Usage  # utility-model tokens for routing (cost only)
    evidence_usage: Usage  # utility-model tokens for the evidence check (cost only)


@dataclass(frozen=True)
class ChatContext:
    """Per-run settings passed with `graph.astream(..., context=ChatContext(...))`."""

    model: str
    user_id: str = ""
    chat_id: str = ""
    timezone: str = "UTC"  # IANA name from the user's browser, e.g. "Asia/Kolkata"
    mode: str = "auto"  # "ask_data" = the user switched on Ask Data for this message
    ask_data_connected: bool = False  # the user has a company session for Ask Data
