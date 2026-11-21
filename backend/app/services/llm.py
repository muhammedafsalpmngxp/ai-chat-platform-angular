"""OpenAI-backed services used by the graph: chat models and moderation.

Both are behind small interfaces so tests (and LangGraph Studio) can swap them.
"""

import logging
from collections.abc import Callable
from typing import Protocol

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI

logger = logging.getLogger("chatbot.llm")

LLMFactory = Callable[[str], BaseChatModel]

# Moderation categories treated as "explicit". Other categories are left to the model.
EXPLICIT_CATEGORIES = ("sexual", "sexual/minors")


class Moderator(Protocol):
    async def is_explicit(self, text: str) -> bool: ...

    async def explicit_flags(self, texts: list[str]) -> list[bool]:
        """One flag per text (one API call for many search results)."""
        ...


class MissingApiKeyError(RuntimeError):
    pass


def openai_llm_factory(api_key: str, timeout: float = 60) -> LLMFactory:
    cache: dict[str, BaseChatModel] = {}

    def factory(model: str) -> BaseChatModel:
        if not api_key:
            raise MissingApiKeyError("OPENAI_API_KEY is not set")
        if model not in cache:
            cache[model] = ChatOpenAI(
                model=model,
                api_key=api_key,
                streaming=True,
                stream_usage=True,  # token counts for the context meter
                max_retries=2,
                timeout=timeout,
            )
        return cache[model]

    return factory


class OpenAIModerator:
    """OpenAI Moderation API. Fails open (logs and allows) if the API is unreachable,
    so a moderation outage does not take the whole chat down."""

    def __init__(self, api_key: str, model: str = "omni-moderation-latest") -> None:
        self._client = AsyncOpenAI(api_key=api_key) if api_key else None
        self._model = model

    async def is_explicit(self, text: str) -> bool:
        return (await self.explicit_flags([text]))[0]

    async def explicit_flags(self, texts: list[str]) -> list[bool]:
        if self._client is None or not texts:
            return [False] * len(texts)
        inputs = [t[:8000] or " " for t in texts]
        try:
            res = await self._client.moderations.create(model=self._model, input=inputs)
        except Exception:  # noqa: BLE001 - any API failure
            logger.warning("Moderation call failed; allowing the content", exc_info=True)
            return [False] * len(texts)
        flags = []
        for result in res.results:
            categories = result.categories.model_dump(by_alias=True)
            flags.append(any(categories.get(name) for name in EXPLICIT_CATEGORIES))
        return flags


class NoopModerator:
    async def is_explicit(self, text: str) -> bool:
        return False

    async def explicit_flags(self, texts: list[str]) -> list[bool]:
        return [False] * len(texts)
