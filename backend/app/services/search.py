"""Web search (Tavily) plus a domain blocklist for explicit sites."""

import logging
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

logger = logging.getLogger("chatbot.search")

# Never shown, and excluded at the Tavily level too.
BLOCKED_DOMAINS = (
    "pornhub.com", "xvideos.com", "xnxx.com", "xhamster.com", "redtube.com", "youporn.com",
    "onlyfans.com", "chaturbate.com", "brazzers.com", "spankbang.com", "eporner.com",
    "rule34.xxx", "e-hentai.org", "nhentai.net", "fansly.com", "stripchat.com",
)
# Social / user-generated sites: fine for opinions, not trustworthy for facts and figures.
LOW_TRUST_DOMAINS = (
    "instagram.com", "facebook.com", "x.com", "twitter.com", "tiktok.com", "pinterest.com",
    "quora.com", "reddit.com", "youtube.com", "threads.net", "linkedin.com", "medium.com",
    "scribd.com", "slideshare.net",
)
# Whole-word markers in the host name (e.g. "xxx" but not "sussex").
_BLOCKED_HOST_WORDS = re.compile(r"(^|[.\-])(porn\w*|xxx|hentai|nsfw|adult|escort\w*)([.\-]|$)", re.I)


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    content: str
    published: str | None = None


class Searcher(Protocol):
    async def search(self, query: str) -> list[SearchResult]: ...


def _host_in(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def is_blocked_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return True
    if _host_in(host, BLOCKED_DOMAINS):
        return True
    return bool(_BLOCKED_HOST_WORDS.search(host))


def is_low_trust_url(url: str) -> bool:
    return _host_in((urlparse(url).hostname or "").lower(), LOW_TRUST_DOMAINS)


class TavilySearcher:
    def __init__(self, api_key: str, max_results: int = 6, depth: str = "advanced") -> None:
        from tavily import AsyncTavilyClient

        self._client = AsyncTavilyClient(api_key=api_key)
        self._max_results = max_results
        self._depth = depth

    async def search(self, query: str) -> list[SearchResult]:
        res = await self._client.search(
            query=query[:400],
            search_depth=self._depth,  # "advanced" = better passages, 2 credits per search
            max_results=self._max_results,
            exclude_domains=list(BLOCKED_DOMAINS + LOW_TRUST_DOMAINS),
            include_answer=False,
            include_raw_content=False,
            timeout=20,
        )
        results = []
        for item in res.get("results", []):
            url = str(item.get("url") or "")
            content = " ".join(str(item.get("content") or "").split())
            if not url or not content:
                continue
            results.append(SearchResult(
                title=str(item.get("title") or url)[:200],
                url=url,
                content=content[:2000],  # keep prompts small; also limits injected text
                published=item.get("published_date"),
            ))
        return results
