"""FastAPI entry point.

Run (from backend/):  uvicorn app.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import InMemorySaver

from app.api import ask_data as ask_data_api
from app.api import attachments as attachments_api
from app.api import config as config_api
from app.api import auth, chats, messages, models
from app.core.config import Settings, get_settings
from app.core.models_catalog import load_catalog
from app.core.rate_limit import AttemptLimiter
from app.graph import build_chat_graph
from app.services.ask_data import AskDataClient, AskDataGateway
from app.services.chat_runner import ChatRunner
from app.services.llm import LLMFactory, Moderator, OpenAIModerator, openai_llm_factory
from app.services.search import Searcher, TavilySearcher
from app.storage import build_chat_repository, build_user_store
from app.storage.attachments import AttachmentStore

logger = logging.getLogger("chatbot")
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")


def _check_settings(settings: Settings) -> None:
    problems = []
    if len(settings.jwt_secret) < 32:
        problems.append("JWT_SECRET must be set to a random string of at least 32 characters")
    if not settings.app_password_hash:
        problems.append("APP_PASSWORD_HASH is empty (run: python scripts/hash_password.py)")
    if problems:
        raise RuntimeError(
            "Invalid backend configuration (check backend/.env):\n  - " + "\n  - ".join(problems)
        )


def create_app(
    settings: Settings | None = None,
    *,
    llm_factory: LLMFactory | None = None,
    moderator: Moderator | None = None,
    searcher: Searcher | None = None,
    ask_data_client: AskDataClient | None = None,
) -> FastAPI:
    """Build the app. Tests pass fakes for the LLM, moderator, search and Ask Data."""
    settings = settings or get_settings()
    _check_settings(settings)
    catalog = load_catalog(settings.models_config_path)  # fail fast on a broken models.yaml
    if not settings.openai_api_key and llm_factory is None:
        logger.warning("OPENAI_API_KEY is not set: chat replies will show a configuration error.")

    llm_factory = llm_factory or openai_llm_factory(
        settings.openai_api_key, settings.llm_timeout_seconds
    )
    moderator = moderator or OpenAIModerator(settings.openai_api_key, settings.moderation_model)
    if searcher is None and settings.tavily_api_key:
        searcher = TavilySearcher(settings.tavily_api_key, settings.search_max_results, settings.search_depth)
    if searcher is None:
        logger.warning("TAVILY_API_KEY is not set: web search questions will be answered without search.")
    if ask_data_client is None and settings.ask_data_enabled:
        ask_data_client = AskDataClient(
            settings.ask_data_auth_url, settings.ask_data_api_url, settings.ask_data_timeout_seconds
        )
    ask_data = AskDataGateway(ask_data_client) if ask_data_client else None
    chat_repo = build_chat_repository(settings)
    attachments = AttachmentStore(
        settings.data_dir,
        max_bytes=settings.max_upload_mb * 1024 * 1024,
        max_files=settings.max_files_per_chat,
        max_chars=settings.max_document_chars,
    )
    checkpointer = InMemorySaver()
    graph = build_chat_graph(
        llm_factory=llm_factory,
        moderator=moderator,
        searcher=searcher,
        attachment_loader=attachments.load,
        assistant_name=settings.assistant_name,
        utility_model=settings.utility_model,
        router_use_llm=settings.router_use_llm,
        history_max_tokens=settings.history_max_tokens,
        search_max_queries=settings.search_max_queries,
        search_max_sources=settings.search_max_sources,
        search_verify=settings.search_verify,
        ask_data=ask_data,
        ask_data_description=settings.ask_data_description,
        ask_data_max_rows=settings.ask_data_max_rows,
        checkpointer=checkpointer,
    )
    runner = ChatRunner(
        graph=graph,
        checkpointer=checkpointer,
        repo=chat_repo,
        llm_factory=llm_factory,
        settings=settings,
        catalog=catalog,
        ask_data=ask_data,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await runner.drain()  # let in-flight replies finish saving

    app = FastAPI(title=settings.app_name, version="0.4.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.chat_repo = chat_repo
    app.state.attachments = attachments
    app.state.ask_data = ask_data
    app.state.user_store = build_user_store(settings)
    app.state.graph = graph
    app.state.chat_runner = runner
    app.state.password_limiter = AttemptLimiter(
        settings.max_password_attempts, settings.password_lockout_minutes * 60
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Error-Code", "Retry-After"],
    )

    app.include_router(auth.router, prefix="/api")
    app.include_router(chats.router, prefix="/api")
    app.include_router(messages.router, prefix="/api")
    app.include_router(attachments_api.router, prefix="/api")
    app.include_router(config_api.router, prefix="/api")
    app.include_router(ask_data_api.router, prefix="/api")
    app.include_router(models.router, prefix="/api")

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok", "storage": settings.storage_backend}

    logger.info("Storage backend: %s", settings.storage_backend)
    return app


app = create_app()
