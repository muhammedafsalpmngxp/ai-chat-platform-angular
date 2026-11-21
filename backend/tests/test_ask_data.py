"""Ask Data route: our backend in the middle of the company's existing server.

A fake company server (httpx.MockTransport) mimics the real contract:
POST /auth/login, POST /auth/refresh-token, POST /api/ai/ask (SSE).
"""

import asyncio
import base64
import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.ask_data import AskDataClient
from tests.conftest import TEST_PASSWORD, make_settings
from tests.fakes import FakeFactory, FakeModerator
from tests.test_chat_stream import parse_sse

COMPANY_EMAIL = "someone@company.example"
COMPANY_PASSWORD = "company-test-password"


def fake_jwt(email: str, exp: float) -> str:
    def b64(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'HS256'})}.{b64({'email': email, 'exp': int(exp)})}.sig"


def sse(*events: tuple[str, object]) -> str:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)


class FakeCompanyServer:
    def __init__(self) -> None:
        self.valid_tokens: set[str] = set()
        self.asks: list[dict] = []
        self.logins = 0
        self.refreshes = 0
        self.expire_next_ask = False
        self.refresh_fails = False
        self.delay_pieces = 0.0

    def _issue(self) -> dict:
        token = fake_jwt(COMPANY_EMAIL, time.time() + 3600) + f".{len(self.valid_tokens)}"
        self.valid_tokens.add(token)
        return {"token": token, "refreshToken": f"refresh-{len(self.valid_tokens)}", "userId": "u1", "tenantId": "t1"}

    def stream_events(self, body: dict):
        n = len(self.asks)
        return [
            ("status", "Understanding the question…"),
            ("sql", "SELECT COUNT(*) AS wells FROM dbo.Wells"),
            ("status", "Running the query…"),
            ("result", {"columns": ["wells"], "rows": [{"wells": 1248}], "totalRows": 1}),
            ("answer", "There are "),
            ("answer", "1,248 wells."),
            ("followups", ["How many are active?", "Wells by plant"]),
            ("done", {"conversationId": "conv-42", "messageId": f"m{n}", "sourceName": "Wells"}),
        ]

    async def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/auth/login":
            body = json.loads(request.content)
            self.logins += 1
            if body == {"email": COMPANY_EMAIL, "password": COMPANY_PASSWORD}:
                return httpx.Response(200, json=self._issue())
            return httpx.Response(401, json={"title": "Unauthorized"})
        if path == "/auth/refresh-token":
            self.refreshes += 1
            if self.refresh_fails:
                return httpx.Response(401)
            return httpx.Response(200, json=self._issue())
        if path == "/api/ai/ask":
            token = request.headers.get("Authorization", "").removeprefix("Bearer ")
            if self.expire_next_ask:
                self.expire_next_ask = False
                self.valid_tokens.discard(token)
            if token not in self.valid_tokens:
                return httpx.Response(401)
            body = json.loads(request.content)
            self.asks.append(body)
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=sse(*self.stream_events(body)))
        return httpx.Response(404)


class Harness:
    def __init__(self, tmp_path: Path, **fake_kwargs) -> None:
        self.company = FakeCompanyServer()
        client = AskDataClient(
            "http://company.test:7007", "http://company.test:5069/api",
            transport=httpx.MockTransport(self.company.handler),
        )
        self.factory = FakeFactory(**fake_kwargs)
        self.moderator = FakeModerator()
        self.app = create_app(
            make_settings(tmp_path, "json"),
            llm_factory=self.factory, moderator=self.moderator, ask_data_client=client,
        )
        self.client = TestClient(self.app)
        token = self.client.post(
            "/api/auth/login", json={"username": "tester", "password": TEST_PASSWORD}
        ).json()["access_token"]
        self.headers = {"Authorization": f"Bearer {token}"}

    def connect(self, password: str = COMPANY_PASSWORD):
        return self.client.post(
            "/api/ask-data/connect", json={"email": COMPANY_EMAIL, "password": password}, headers=self.headers
        )

    def new_chat(self) -> str:
        return self.client.post("/api/chats", json={}, headers=self.headers).json()["id"]

    def send(self, chat_id: str, content: str, **extra) -> list[tuple[str, dict]]:
        res = self.client.post(
            f"/api/chats/{chat_id}/messages", json={"content": content, **extra}, headers=self.headers
        )
        assert res.status_code == 200, res.text
        return parse_sse(res.text)

    def chat(self, chat_id: str) -> dict:
        return self.client.get(f"/api/chats/{chat_id}", headers=self.headers).json()


@pytest.fixture
def h(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def test_connect_status_disconnect(h: Harness) -> None:
    status = h.client.get("/api/ask-data/status", headers=h.headers).json()
    assert status == {"enabled": True, "connected": False, "email": None}

    bad = h.connect("wrong")
    assert bad.status_code == 400 and "Incorrect" in bad.json()["detail"]

    ok = h.connect()
    assert ok.status_code == 200
    assert ok.json() == {"enabled": True, "connected": True, "email": COMPANY_EMAIL}
    # The password is not echoed or stored anywhere in the app state.
    assert COMPANY_PASSWORD not in json.dumps(ok.json())

    assert h.client.post("/api/ask-data/disconnect", headers=h.headers).json()["connected"] is False
    assert h.client.post("/api/ask-data/connect", json={"email": COMPANY_EMAIL, "password": COMPANY_PASSWORD}).status_code == 401


def test_ask_data_mode_streams_answer_sql_and_table(h: Harness) -> None:
    h.connect()
    chat_id = h.new_chat()
    events = h.send(chat_id, "How many wells are there?", mode="ask_data")

    # Routed straight to ask_data (no router LLM call, no OpenAI answer).
    assert h.factory.model.router_calls == [] and h.factory.model.calls == []
    steps = [d for e, d in events if e == "step"]
    assert [s["node"] for s in steps if s["status"] == "running" and "detail" not in s] == [
        "input_guard", "router", "ask_data",
    ]
    details = [s["detail"] for s in steps if s.get("detail")]
    assert details == ["Understanding the question…", "Wrote the SQL query", "Running the query…", "Got 1 rows"]

    # The company answer streams as tokens.
    assert "".join(d["text"] for e, d in events if e == "token") == "There are 1,248 wells."
    done = next(d for e, d in events if e == "done")
    message = done["message"]
    assert message["content"] == "There are 1,248 wells."
    assert message["model"] == "ask-data"
    assert message["data"]["sql"] == "SELECT COUNT(*) AS wells FROM dbo.Wells"
    assert message["data"]["columns"] == ["wells"] and message["data"]["rows"] == [{"wells": 1248}]
    assert message["data"]["followups"] == ["How many are active?", "Wells by plant"]
    assert message["data"]["source_name"] == "Wells"

    # What we sent to the company server.
    assert h.company.asks[0] == {
        "question": "How many wells are there?", "conversationId": None, "sourceType": None, "sourceId": None,
    }
    # Company data never went to OpenAI: no output moderation of the answer, no LLM title.
    assert "There are 1,248 wells." not in h.moderator.checked
    title = next(d for e, d in events if e == "title")["chat"]["title"]
    assert title == "How many wells are there?"

    # Saved with the chat.
    saved = h.chat(chat_id)["messages"][-1]
    assert saved["data"]["total_rows"] == 1


def test_follow_up_reuses_company_conversation(tmp_path: Path) -> None:
    first = Harness(tmp_path)
    first.connect()
    chat_id = first.new_chat()
    first.send(chat_id, "How many wells are there?", mode="ask_data")
    first.send(chat_id, "How many are active?", mode="ask_data")
    assert first.company.asks[1]["conversationId"] == "conv-42"

    # After a backend restart the conversation id is restored from the saved chat.
    second = Harness(tmp_path)
    second.connect()
    second.send(chat_id, "And by plant?", mode="ask_data")
    assert second.company.asks[0]["conversationId"] == "conv-42"


def test_expired_token_is_refreshed_and_retried(h: Harness) -> None:
    h.connect()
    h.company.expire_next_ask = True
    chat_id = h.new_chat()
    done = next(d for e, d in h.send(chat_id, "How many wells?", mode="ask_data") if e == "done")
    assert done["message"]["content"] == "There are 1,248 wells."
    assert h.company.refreshes == 1 and len(h.company.asks) == 1


def test_failed_refresh_disconnects_and_explains(h: Harness) -> None:
    h.connect()
    h.company.expire_next_ask = True
    h.company.refresh_fails = True
    chat_id = h.new_chat()
    events = h.send(chat_id, "How many wells?", mode="ask_data")
    assert "connect your company account" in next(d for e, d in events if e == "replace")["text"]
    assert h.client.get("/api/ask-data/status", headers=h.headers).json()["connected"] is False


def test_not_connected_says_how_to_connect(h: Harness) -> None:
    chat_id = h.new_chat()
    events = h.send(chat_id, "How many wells?", mode="ask_data")
    assert "Settings" in next(d for e, d in events if e == "replace")["text"]
    assert h.company.asks == []


def test_router_can_choose_ask_data_only_when_connected(tmp_path: Path) -> None:
    h = Harness(tmp_path, router_intent="ask_data")
    chat_id = h.new_chat()
    h.send(chat_id, "How many wells do we have in plant A?")
    # Not connected: ask_data is not offered to the router, and its answer is ignored.
    router_system = str(h.factory.model.router_calls[-1][0].content)
    assert "ask_data" not in router_system
    assert h.company.asks == []

    h.connect()
    h.send(chat_id, "How many wells do we have in plant A?")
    router_system = str(h.factory.model.router_calls[-1][0].content)
    assert '- ask_data: questions about' in router_system
    assert len(h.company.asks) == 1


def test_company_server_down_gives_friendly_error(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.connect()

    async def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    h.app.state.ask_data._client._transport = httpx.MockTransport(down)
    chat_id = h.new_chat()
    events = h.send(chat_id, "How many wells?", mode="ask_data")
    text = next(d for e, d in events if e == "replace")["text"]
    assert "could not answer" in text and "company server" in text


def test_ask_data_disabled_without_urls(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, "json"), llm_factory=FakeFactory(), moderator=FakeModerator())
    client = TestClient(app)
    token = client.post("/api/auth/login", json={"username": "tester", "password": TEST_PASSWORD}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/ask-data/status", headers=headers).json()["enabled"] is False
    assert client.post("/api/ask-data/connect", json={"email": "a@b.c", "password": "x"}, headers=headers).status_code == 503
    assert client.get("/api/config", headers=headers).json()["ask_data_enabled"] is False


class NumericIdCompany(FakeCompanyServer):
    """Like the real server: numeric ids, a chart spec, rows as lists, columns as objects."""

    def stream_events(self, body):
        n = len(self.asks)
        if "pie" in body["question"]:
            return [
                ("status", "Running the query…"),
                ("sql", {"sql": "SELECT Cluster, COUNT(*) AS Wells FROM Wells GROUP BY Cluster"}),
                ("result", {"columns": [{"name": "Cluster"}, {"name": "Wells"}],
                            "rows": [["North", 120], ["South", 80]], "totalRows": 2}),
                ("chartspec", {"type": "pie", "title": "Wells by cluster"}),
                ("done", {"conversationId": 4521, "messageId": 900 + n, "sourceName": "Wells"}),
            ]
        return [
            ("answer", {"text": "There are 6,982 wells."}),
            ("done", {"conversationId": 4521, "messageId": 900 + n, "sourceName": "Wells"}),
        ]


def test_numeric_ids_and_chart_request_are_saved(tmp_path: Path) -> None:
    """Regression: numeric conversation ids crashed saving, so turns vanished and later
    answers came back empty."""
    h = Harness(tmp_path)
    h.company = NumericIdCompany()
    h.app.state.ask_data._client._transport = httpx.MockTransport(h.company.handler)
    h.connect()
    chat_id = h.new_chat()

    first = h.send(chat_id, "how many wells are there", mode="ask_data")
    assert next(d for e, d in first if e == "done")["message"]["content"] == "There are 6,982 wells."

    events = h.send(chat_id, "give me in pie chart as wells in each cluster", mode="ask_data")
    assert not any(e == "error" for e, _ in events)
    message = next(d for e, d in events if e == "done")["message"]
    assert message["content"] == "Here is the chart."
    data = message["data"]
    assert data["chart_type"] == "pie" and data["chart_title"] == "Wells by cluster"
    assert data["columns"] == ["Cluster", "Wells"]
    assert data["rows"] == [{"Cluster": "North", "Wells": 120}, {"Cluster": "South", "Wells": 80}]
    assert data["sql"].startswith("SELECT Cluster")
    assert data["conversation_id"] == "4521"  # stored as text

    # The follow-up reused the company conversation, and every turn was saved.
    assert h.company.asks[1]["conversationId"] == "4521"
    assert [m["role"] for m in h.chat(chat_id)["messages"]] == ["user", "assistant"] * 2


def test_chart_hint_from_question_without_chartspec(h: Harness) -> None:
    from app.graph.builder import _chart_hint

    assert _chart_hint("give me in pie chart as wells in each cluster") == "pie"
    assert _chart_hint("bar graph of production by plant") == "bar"
    assert _chart_hint("plot wells per year") == "bar"
    assert _chart_hint("line chart of output") == "line"
    assert _chart_hint("how many wells are there") is None

    h.connect()
    chat_id = h.new_chat()
    events = h.send(chat_id, "how many wells as a bar chart", mode="ask_data")
    assert next(d for e, d in events if e == "done")["message"]["data"]["chart_type"] == "bar"


def test_unexpected_result_shape_never_breaks_saving(tmp_path: Path) -> None:
    class OddCompany(FakeCompanyServer):
        def stream_events(self, body):
            return [
                ("result", {"columns": "not-a-list", "rows": "nope", "totalRows": "many"}),
                ("followups", [{"question": "Next?"}, 3, None]),
                ("answer", "Done."),
                ("done", {"conversationId": {"weird": True}}),
            ]

    h = Harness(tmp_path)
    h.company = OddCompany()
    h.app.state.ask_data._client._transport = httpx.MockTransport(h.company.handler)
    h.connect()
    chat_id = h.new_chat()
    events = h.send(chat_id, "anything", mode="ask_data")
    assert next(d for e, d in events if e == "done")["message"]["content"] == "Done."
    assert len(h.chat(chat_id)["messages"]) == 2


def test_sse_parser_handles_split_chunks() -> None:
    from app.services.ask_data import _parse_sse_block

    assert _parse_sse_block('event: answer\ndata: "hi"') == ("answer", "hi")
    assert _parse_sse_block("event: status\ndata: plain text") == ("status", "plain text")
    assert _parse_sse_block("data: x") is None
