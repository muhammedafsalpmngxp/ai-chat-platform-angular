"""Client for the company's existing "Ask Data" agent (text-to-SQL), used as-is.

    our backend --POST /auth/login----------> auth service (e.g. :7007)  -> {token, refreshToken}
                --POST /ai/ask (Bearer)-----> tenant API   (e.g. :5069)  -> SSE stream:
                      status / spec / sql / result / answer (text pieces) / followups /
                      clarify / insights / chartspec / choices / trace / error / done

The browser never talks to the company server: no CORS issues, and the company
token stays on our backend (in memory only). Passwords are never stored.
"""

import asyncio
import base64
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace

import httpx

logger = logging.getLogger("chatbot.ask_data")


class AskDataError(Exception):
    """The company server failed or returned something unexpected."""


class AskDataAuthError(AskDataError):
    """Wrong credentials, or the session expired and could not be renewed."""


class AskDataNotConnected(AskDataError):
    """The user has not connected a company account (or it was disconnected)."""


@dataclass(frozen=True)
class AskDataSession:
    token: str
    refresh_token: str
    email: str
    expires_at: float | None = None  # from the JWT "exp" claim, if present


def _jwt_claims(token: str) -> dict:
    """Read (not verify) JWT claims - only used for display and expiry hints."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return data if isinstance(data, dict) else {}
    except (IndexError, ValueError):
        return {}


def _session_from(body: object, fallback_email: str) -> AskDataSession:
    if not isinstance(body, dict):
        raise AskDataError("The company server sent an unexpected login response.")
    token, refresh = body.get("token"), body.get("refreshToken")
    if not isinstance(token, str) or not token.strip() or not isinstance(refresh, str):
        raise AskDataError("The company server's login response is missing tokens.")
    claims = _jwt_claims(token)
    exp = claims.get("exp")
    return AskDataSession(
        token=token,
        refresh_token=refresh,
        email=str(claims.get("email") or body.get("email") or fallback_email),
        expires_at=float(exp) if isinstance(exp, (int, float)) else None,
    )


class AskDataClient:
    def __init__(
        self,
        auth_url: str,
        api_url: str,
        timeout: float = 180,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._auth_url = auth_url.rstrip("/")
        self._api_url = api_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout, connect=15)
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    async def login(self, email: str, password: str) -> AskDataSession:
        try:
            async with self._client() as client:
                res = await client.post(f"{self._auth_url}/auth/login", json={"email": email, "password": password})
        except httpx.HTTPError as exc:
            raise AskDataError("Could not reach the company server.") from exc
        if res.status_code in (400, 401, 403):
            raise AskDataAuthError("Incorrect company email or password.")
        if res.status_code >= 400:
            raise AskDataError(f"The company login failed (HTTP {res.status_code}).")
        return _session_from(res.json(), email)

    async def refresh(self, session: AskDataSession) -> AskDataSession:
        try:
            async with self._client() as client:
                res = await client.post(
                    f"{self._auth_url}/auth/refresh-token", json={"refreshToken": session.refresh_token}
                )
        except httpx.HTTPError as exc:
            raise AskDataError("Could not reach the company server.") from exc
        if res.status_code >= 400:
            raise AskDataAuthError("The company session expired. Please connect again.")
        return replace(_session_from(res.json(), session.email), email=session.email)

    async def ask(
        self,
        session: AskDataSession,
        question: str,
        conversation_id: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> AsyncIterator[tuple[str, object]]:
        """Yield (event, data) pairs from the SSE stream. Raises AskDataAuthError on 401
        before anything is yielded, so the caller can refresh and retry."""
        body = {
            "question": question,
            "conversationId": conversation_id,
            "sourceType": source_type,
            "sourceId": source_id,
        }
        headers = {"Authorization": f"Bearer {session.token}", "Accept": "text/event-stream"}
        try:
            async with self._client() as client:
                async with client.stream("POST", f"{self._api_url}/ai/ask", json=body, headers=headers) as res:
                    if res.status_code == 401:
                        raise AskDataAuthError("The company session expired.")
                    if res.status_code >= 400:
                        await res.aread()
                        raise AskDataError(f"The company server refused the question (HTTP {res.status_code}).")
                    buffer = ""
                    async for chunk in res.aiter_text():
                        buffer += chunk.replace("\r\n", "\n")
                        while "\n\n" in buffer:
                            block, buffer = buffer.split("\n\n", 1)
                            event = _parse_sse_block(block)
                            if event:
                                yield event
                    if buffer.strip():
                        event = _parse_sse_block(buffer)
                        if event:
                            yield event
        except httpx.HTTPError as exc:
            raise AskDataError("Lost the connection to the company server.") from exc


def _parse_sse_block(block: str) -> tuple[str, object] | None:
    event, data_lines = None, []
    for line in block.split("\n"):
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].removeprefix(" "))
    if not event or not data_lines:
        return None
    raw = "\n".join(data_lines)
    try:
        return event, json.loads(raw)
    except json.JSONDecodeError:
        return event, raw


class AskDataGateway:
    """Per-user company sessions (in memory) + asking with automatic token renewal."""

    def __init__(self, client: AskDataClient) -> None:
        self._client = client
        self._sessions: dict[str, AskDataSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, user_id: str) -> asyncio.Lock:
        return self._locks.setdefault(user_id, asyncio.Lock())

    def session(self, user_id: str) -> AskDataSession | None:
        return self._sessions.get(user_id)

    def is_connected(self, user_id: str) -> bool:
        return user_id in self._sessions

    async def connect(self, user_id: str, email: str, password: str) -> AskDataSession:
        session = await self._client.login(email, password)
        self._sessions[user_id] = session
        return session

    def disconnect(self, user_id: str) -> None:
        self._sessions.pop(user_id, None)

    async def _fresh_session(self, user_id: str, stale: AskDataSession) -> AskDataSession:
        async with self._lock(user_id):
            current = self._sessions.get(user_id)
            if current is None:
                raise AskDataNotConnected
            if current.token != stale.token:
                return current  # someone else already renewed it
            try:
                renewed = await self._client.refresh(current)
            except AskDataAuthError:
                self._sessions.pop(user_id, None)
                raise
            self._sessions[user_id] = renewed
            return renewed

    async def ask(
        self, user_id: str, question: str, conversation_id: str | None = None
    ) -> AsyncIterator[tuple[str, object]]:
        session = self._sessions.get(user_id)
        if session is None:
            raise AskDataNotConnected
        # Renew a token that is about to expire before starting.
        if session.expires_at and session.expires_at - time.time() < 30:
            session = await self._fresh_session(user_id, session)
        for attempt in (1, 2):
            started = False
            try:
                async for event in self._client.ask(session, question, conversation_id):
                    started = True
                    yield event
                return
            except AskDataAuthError:
                if started or attempt == 2:
                    raise
                session = await self._fresh_session(user_id, session)
