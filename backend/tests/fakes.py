"""Fake LLM, moderator and search so graph/API tests run without OpenAI or Tavily."""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from app.services.llm import MissingApiKeyError
from app.services.search import SearchResult


class FakeChat(BaseChatModel):
    reply: str = "Hello there, how can I help?"
    title: str = "Friendly Greeting Chat"
    router_intent: str = "chitchat"
    router_query: str = ""
    router_queries: list[str] = []
    evidence_reply: str = json.dumps({
        "candidates": [{"name": "Film X", "value": "350 crore", "basis": "worldwide gross", "sources": [1]}],
        "answer": "Film X is the top grosser.",
        "conflicts": "",
        "confidence": "high",
    })
    delay: float = 0.0
    calls: list[list[BaseMessage]] = []
    router_calls: list[list[BaseMessage]] = []
    evidence_calls: list[list[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "fake-chat"

    def _answer(self, messages: list[BaseMessage]) -> str:
        first = messages[0] if messages else None
        system = str(first.content) if isinstance(first, SystemMessage) else ""
        if "word title" in system:
            return self.title
        if "Classify the user's latest message" in system:
            self.router_calls.append(list(messages))
            queries = self.router_queries or ([self.router_query] if self.router_query else [])
            return json.dumps({"intent": self.router_intent, "search_queries": queries})
        if "You check web search results" in system:
            self.evidence_calls.append(list(messages))
            return self.evidence_reply
        self.calls.append(list(messages))
        return self.reply

    def _generate(self, messages, stop=None, run_manager: CallbackManagerForLLMRun | None = None, **kw: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self._answer(messages)))])

    def _stream(self, messages, stop=None, run_manager=None, **kw) -> Iterator[ChatGenerationChunk]:
        raise NotImplementedError

    async def _astream(
        self, messages, stop=None, run_manager: AsyncCallbackManagerForLLMRun | None = None, **kw: Any
    ) -> AsyncIterator[ChatGenerationChunk]:
        text = self._answer(messages)
        words = text.split(" ")
        for i, word in enumerate(words):
            if self.delay:
                await asyncio.sleep(self.delay)
            piece = word if i == 0 else " " + word
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=piece))
            if run_manager:
                await run_manager.on_llm_new_token(piece, chunk=chunk)
            yield chunk
        usage = {
            "input_tokens": 100,
            "output_tokens": len(words),
            "total_tokens": 100 + len(words),
            "input_token_details": {"cache_read": 40},
        }
        yield ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata=usage))


class FakeFactory:
    def __init__(self, **kwargs: Any) -> None:
        self.model = FakeChat(calls=[], router_calls=[], evidence_calls=[], **kwargs)
        self.models_requested: list[str] = []
        self.missing_key = False

    def __call__(self, model: str) -> BaseChatModel:
        if self.missing_key:
            raise MissingApiKeyError("no key")
        self.models_requested.append(model)
        return self.model


class FakeModerator:
    """Flags any text containing the word EXPLICIT."""

    def __init__(self) -> None:
        self.checked: list[str] = []

    async def is_explicit(self, text: str) -> bool:
        return (await self.explicit_flags([text]))[0]

    async def explicit_flags(self, texts: list[str]) -> list[bool]:
        self.checked.extend(texts)
        return ["EXPLICIT" in t for t in texts]


class FakeSearcher:
    def __init__(self, results: list[SearchResult] | None = None, fail: bool = False) -> None:
        self.results = results if results is not None else [
            SearchResult(
                title="Highest-grossing Malayalam films - 2026 update",
                url="https://example.com/mollywood-box-office",
                content="As of 2026 the top Malayalam grosser is Film X with 350 crore worldwide.",
                published="2026-11-01",
            ),
            SearchResult(title="Box office news", url="https://news.example.org/bo", content="Film Y is second."),
        ]
        self.fail = fail
        self.queries: list[str] = []

    async def search(self, query: str) -> list[SearchResult]:
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("search down")
        return list(self.results)
