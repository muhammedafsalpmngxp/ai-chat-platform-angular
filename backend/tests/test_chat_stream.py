import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.chat_runner import ChatBusyError
from tests.conftest import TEST_PASSWORD, make_settings
from tests.fakes import FakeFactory, FakeModerator


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


class Harness:
    def __init__(self, tmp_path: Path, settings: dict | None = None, searcher=None, **fake_kwargs) -> None:
        self.settings = make_settings(tmp_path, "json", **(settings or {}))
        self.factory = FakeFactory(**fake_kwargs)
        self.moderator = FakeModerator()
        self.searcher = searcher
        self.app = create_app(
            self.settings, llm_factory=self.factory, moderator=self.moderator, searcher=searcher
        )
        self.client = TestClient(self.app)
        token = self.client.post(
            "/api/auth/login", json={"username": "tester", "password": TEST_PASSWORD}
        ).json()["access_token"]
        self.headers = {"Authorization": f"Bearer {token}"}

    def new_chat(self) -> str:
        return self.client.post("/api/chats", json={}, headers=self.headers).json()["id"]

    def send(self, chat_id: str, content: str, **extra) -> list[tuple[str, dict]]:
        res = self.client.post(
            f"/api/chats/{chat_id}/messages", json={"content": content, **extra}, headers=self.headers
        )
        assert res.status_code == 200, res.text
        assert res.headers["content-type"].startswith("text/event-stream")
        return parse_sse(res.text)

    def chat(self, chat_id: str) -> dict:
        return self.client.get(f"/api/chats/{chat_id}", headers=self.headers).json()


@pytest.fixture
def h(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def test_streams_tokens_and_saves_reply(h: Harness) -> None:
    chat_id = h.new_chat()
    events = h.send(chat_id, "Tell me something nice")
    names = [e for e, _ in events]

    assert names[0] == "start"
    assert names.count("token") == len(h.factory.model.reply.split(" "))
    assert "".join(d["text"] for e, d in events if e == "token") == h.factory.model.reply
    done = next(d for e, d in events if e == "done")
    assert done["message"]["content"] == h.factory.model.reply
    assert done["message"]["model"] == "gpt-6-luna"  # default model
    assert done["chat"]["token_count"] == 100 + 6
    assert done["chat"]["total_cached_input_tokens"] == 40

    # First turn gets an auto title.
    title = next(d for e, d in events if e == "title")
    assert title["chat"]["title"] == "Friendly Greeting Chat"

    chat = h.chat(chat_id)
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]
    assert chat["title"] == "Friendly Greeting Chat"


def test_second_turn_sends_history_and_adds_usage(h: Harness) -> None:
    chat_id = h.new_chat()
    h.send(chat_id, "First question here")
    events = h.send(chat_id, "Second question here")
    assert not any(e == "title" for e, _ in events)  # title only on the first turn

    prompt = h.factory.model.calls[-1]
    assert [type(m).__name__ for m in prompt] == ["SystemMessage", "HumanMessage", "AIMessage", "HumanMessage"]
    chat = h.chat(chat_id)
    assert len(chat["messages"]) == 4
    assert chat["total_input_tokens"] == 200


def test_history_is_restored_from_json_after_restart(tmp_path: Path) -> None:
    first = Harness(tmp_path)
    chat_id = first.new_chat()
    first.send(chat_id, "Remember the word pineapple")

    second = Harness(tmp_path)  # new app instance = empty checkpointer
    second.send(chat_id, "What word did I say?")
    prompt = second.factory.model.calls[-1]
    assert "pineapple" in str(prompt[1].content)
    assert len(second.chat(chat_id)["messages"]) == 4


def test_trivial_messages_skip_moderation(h: Harness) -> None:
    chat_id = h.new_chat()
    h.send(chat_id, "hi!")
    # Only the output guard ran moderation (on the reply), not the input guard.
    assert h.moderator.checked == [h.factory.model.reply]


def test_explicit_input_is_refused_without_calling_the_model(h: Harness) -> None:
    chat_id = h.new_chat()
    events = h.send(chat_id, "show me EXPLICIT things")
    replace = next(d for e, d in events if e == "replace")
    assert replace["status"] == "refused"
    assert "explicit content" in replace["text"]
    assert not any(e == "token" for e, _ in events)
    assert h.factory.model.calls == []
    assert h.chat(chat_id)["messages"][-1]["status"] == "refused"


def test_explicit_output_is_replaced(tmp_path: Path) -> None:
    h = Harness(tmp_path, reply="some EXPLICIT answer")
    chat_id = h.new_chat()
    events = h.send(chat_id, "innocent question")
    assert any(e == "token" for e, _ in events)
    assert next(d for e, d in events if e == "replace")["status"] == "refused"
    saved = h.chat(chat_id)["messages"]
    assert len(saved) == 2 and saved[-1]["status"] == "refused"
    assert "EXPLICIT" not in saved[-1]["content"]


def test_missing_api_key_reports_error_and_keeps_question(h: Harness) -> None:
    h.factory.missing_key = True
    chat_id = h.new_chat()
    events = h.send(chat_id, "Are you there?")
    error = next(d for e, d in events if e == "error")
    assert "OPENAI_API_KEY" in error["detail"]
    assert [m["role"] for m in h.chat(chat_id)["messages"]] == ["user"]


def test_model_validation(h: Harness) -> None:
    chat_id = h.new_chat()
    url = f"/api/chats/{chat_id}/messages"
    assert h.client.post(url, json={"content": "x", "model": "nope"}, headers=h.headers).status_code == 400
    premium = h.client.post(url, json={"content": "x", "model": "gpt-6.2-astra"}, headers=h.headers)
    assert premium.status_code == 403
    assert premium.headers["X-Error-Code"] == "reauth_required"
    assert h.client.post(url, json={"content": "   "}, headers=h.headers).status_code == 422
    assert h.client.post("/api/chats/missing/messages", json={"content": "x"}, headers=h.headers).status_code == 404
    events = h.send(chat_id, "hello world friend", model="gpt-6.1-terra")
    assert next(d for e, d in events if e == "done")["message"]["model"] == "gpt-6.1-terra"


def test_unlock_and_access_tokens_are_not_interchangeable(h: Harness) -> None:
    chat_id = h.new_chat()
    unlock = h.client.post(
        "/api/auth/reauth", json={"password": TEST_PASSWORD}, headers=h.headers
    ).json()["unlock_token"]

    # The access token is not accepted as an unlock token, and vice versa.
    access = h.headers["Authorization"].removeprefix("Bearer ")
    bad = h.client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "hello", "model": "gpt-6.2-astra"},
        headers={**h.headers, "X-Premium-Unlock": access},
    )
    assert bad.status_code == 403
    assert h.client.get("/api/chats", headers={"Authorization": f"Bearer {unlock}"}).status_code == 401


def test_premium_send_with_unlock(tmp_path: Path) -> None:
    h = Harness(tmp_path, settings={"router_use_llm": False})
    chat_id = h.new_chat()
    unlock = h.client.post(
        "/api/auth/reauth", json={"password": TEST_PASSWORD}, headers=h.headers
    ).json()["unlock_token"]
    res = h.client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "hello there", "model": "gpt-6.2-astra"},
        headers={**h.headers, "X-Premium-Unlock": unlock},
    )
    assert res.status_code == 200
    done = next(d for e, d in parse_sse(res.text) if e == "done")
    assert done["message"]["model"] == "gpt-6.2-astra"
    # 100 input (40 cached) + one output token per word, at Astra prices ($8 / $0.40 / $40 per 1M).
    words = len(h.factory.model.reply.split(" "))
    expected = (60 * 8.00 + 40 * 0.40 + words * 40.00) / 1_000_000
    assert abs(done["chat"]["total_cost_usd"] - expected) < 1e-9


def test_cost_accumulates_per_turn_model(tmp_path: Path) -> None:
    h = Harness(tmp_path, settings={"router_use_llm": False})
    chat_id = h.new_chat()
    h.send(chat_id, "first turn", model="gpt-6-luna")
    h.send(chat_id, "second turn", model="gpt-6.1-terra")
    words = len(h.factory.model.reply.split(" "))
    luna = (60 * 0.10 + 40 * 0.01 + words * 0.50) / 1_000_000
    terra = (60 * 1.00 + 40 * 0.05 + words * 5.00) / 1_000_000
    chat = h.chat(chat_id)
    assert abs(chat["total_cost_usd"] - (luna + terra)) < 1e-9
    assert chat["model"] == "gpt-6.1-terra"


def test_stop_saves_partial_answer_and_busy_guard(tmp_path: Path) -> None:
    h = Harness(tmp_path, reply="one two three four five six seven eight", delay=0.05)
    chat_id = h.new_chat()
    runner = h.app.state.chat_runner
    user = h.app.state.user_store.get_user("u-tester")

    async def scenario() -> None:
        chat = await h.app.state.chat_repo.get_chat(user.id, chat_id)
        events = runner.start_turn(user, chat, "count please", "gpt-6-luna")
        with pytest.raises(ChatBusyError):
            runner.start_turn(user, chat, "again", "gpt-6-luna")
        tokens = 0
        async for event in events:
            if event["event"] == "token":
                tokens += 1
                if tokens == 3:
                    break  # like the client pressing Stop
        await events.aclose()
        await runner.drain()

    asyncio.run(scenario())
    messages = h.chat(chat_id)["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[-1]["status"] == "stopped"
    assert messages[-1]["content"].startswith("one two three")
    assert messages[-1]["content"] != "one two three four five six seven eight"

    # The thread continues normally after a stop.
    h.factory.model.delay = 0
    h.send(chat_id, "go on")
    assert len(h.chat(chat_id)["messages"]) == 4


def test_delete_forgets_thread(h: Harness) -> None:
    chat_id = h.new_chat()
    h.send(chat_id, "something to forget")
    runner = h.app.state.chat_runner
    config = {"configurable": {"thread_id": runner.thread_id("u-tester", chat_id)}}

    async def messages() -> list:
        return (await h.app.state.graph.aget_state(config)).values.get("messages", [])

    assert asyncio.run(messages())
    assert h.client.delete(f"/api/chats/{chat_id}", headers=h.headers).status_code == 204
    assert asyncio.run(messages()) == []
