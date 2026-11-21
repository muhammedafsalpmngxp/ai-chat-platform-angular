"""Entry point for LangGraph tooling (langgraph.json -> LangGraph Studio / `langgraph dev`).

The tooling supplies its own checkpointer, so none is attached here.
"""

from app.core.config import get_settings
from app.graph.builder import build_chat_graph
from app.services.llm import OpenAIModerator, openai_llm_factory
from app.services.search import TavilySearcher
from app.storage.attachments import AttachmentStore


def make_graph():
    settings = get_settings()
    attachments = AttachmentStore(
        settings.data_dir,
        max_bytes=settings.max_upload_mb * 1024 * 1024,
        max_files=settings.max_files_per_chat,
        max_chars=settings.max_document_chars,
    )
    return build_chat_graph(
        llm_factory=openai_llm_factory(settings.openai_api_key, settings.llm_timeout_seconds),
        moderator=OpenAIModerator(settings.openai_api_key, settings.moderation_model),
        searcher=TavilySearcher(settings.tavily_api_key, settings.search_max_results, settings.search_depth)
        if settings.tavily_api_key
        else None,
        attachment_loader=attachments.load,
        assistant_name=settings.assistant_name,
        utility_model=settings.utility_model,
        router_use_llm=settings.router_use_llm,
        history_max_tokens=settings.history_max_tokens,
        search_max_queries=settings.search_max_queries,
        search_max_sources=settings.search_max_sources,
        search_verify=settings.search_verify,
    )
