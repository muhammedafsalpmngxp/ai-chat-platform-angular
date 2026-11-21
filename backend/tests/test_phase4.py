"""Router, web search, realtime, date/time context and file uploads."""

import io
import json
import struct
import zlib
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from app.graph.rules import is_realtime, likely_needs_search
from app.services.search import SearchResult, is_blocked_url
from tests.fakes import FakeSearcher
from tests.test_chat_stream import Harness, h  # noqa: F401 - `h` is a fixture


def tiny_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")


def system_texts(prompt) -> list[str]:
    return [str(m.content) for m in prompt if isinstance(m, SystemMessage)]


# ------------------------------------------------------------------ rules


def test_rules() -> None:
    assert is_realtime("what's the weather in Kochi today?")
    assert is_realtime("Bitcoin price right now")
    assert not is_realtime("explain how weather satellites work")  # left to the router
    assert likely_needs_search("most grossed movie in mollywood")
    assert likely_needs_search("latest iPhone")
    assert not likely_needs_search("write a poem about rain")
    assert is_blocked_url("https://www.pornhub.com/x")
    assert is_blocked_url("https://free-porn-site.net/a")
    assert not is_blocked_url("https://www.sussex.ac.uk/news")
    assert not is_blocked_url("https://en.wikipedia.org/wiki/Malayalam_cinema")


# ------------------------------------------------------------- web search


def test_web_search_research_evidence_synthesizer(tmp_path: Path) -> None:
    searcher = FakeSearcher()
    h = Harness(
        tmp_path,
        searcher=searcher,
        router_intent="web_search",
        router_queries=["highest grossing Malayalam film 2026", "list of highest-grossing Malayalam films"],
        reply="Film X is the top grosser [1][2], ahead of Film Y [2].",
    )
    chat_id = h.new_chat()
    events = h.send(chat_id, "most grossed movie in mollywood", timezone="Asia/Kolkata")

    # Live LangGraph progress: every node starts and finishes, in graph order.
    steps = [d for e, d in events if e == "step"]
    order = [s["node"] for s in steps if s["status"] == "running" and "detail" not in s]
    assert order == ["input_guard", "router", "web_search", "evidence", "synthesizer", "output_guard"]
    details = [s["detail"] for s in steps if s.get("detail")]
    assert details[0].startswith('Searching: "highest grossing Malayalam film 2026" | "list of')
    assert "Collected 2 sources" in details  # same 2 pages from both queries, de-duplicated
    assert "Comparing 2 sources" in details and "Confidence: high" in details
    names = [e for e, _ in events]
    assert names.index("step") < names.index("token")

    # Both queries ran; duplicates merged.
    assert searcher.queries == ["highest grossing Malayalam film 2026", "list of highest-grossing Malayalam films"]

    # The evidence check saw every result before anything was written.
    evidence_prompt = h.factory.model.evidence_calls[-1]
    assert "most grossed movie in mollywood" in str(evidence_prompt[1].content)
    assert "350 crore" in str(evidence_prompt[1].content)

    # The synthesizer got the checked notes + results right before the question.
    prompt = h.factory.model.calls[-1]
    systems = system_texts(prompt)
    assert "Asia/Kolkata" in systems[0] and "2026" in systems[0]  # date + timezone
    assert "Answer-writing instructions" in systems[1]
    assert "<verified_notes>" in systems[2] and "Confidence: high" in systems[2]
    assert "<search_results>" in systems[2] and "350 crore" in systems[2]
    assert isinstance(prompt[-1], HumanMessage)

    # Citation markers are removed; the cleaned text replaces the streamed one.
    done = next(d for e, d in events if e == "done")
    assert done["message"]["content"] == "Film X is the top grosser, ahead of Film Y."
    assert next(d for e, d in events if e == "replace")["text"] == done["message"]["content"]
    assert done["message"]["confidence"] == "high"
    assert [s["url"] for s in done["message"]["sources"]] == [
        "https://example.com/mollywood-box-office",
        "https://news.example.org/bo",
    ]

    # Sources are saved with the chat and survive reload.
    saved = h.chat(chat_id)["messages"][-1]
    assert len(saved["sources"]) == 2
    # Search results are not stored in the conversation itself.
    assert all("<search_results>" not in m["content"] for m in h.chat(chat_id)["messages"])


def test_citation_stripping() -> None:
    from app.graph.builder import strip_citations

    assert strip_citations("Dangal leads [1][4]. Baahubali 2 is Telugu [3, 5].") == "Dangal leads. Baahubali 2 is Telugu."
    assert strip_citations("See [2-3] and [docs](https://x.y)") == "See and [docs](https://x.y)"
    assert strip_citations("arr[0] stays? no digits >2: [123]") == "arr stays? no digits >2: [123]"


def test_evidence_failure_still_answers(tmp_path: Path) -> None:
    h = Harness(tmp_path, searcher=FakeSearcher(), router_intent="web_search", evidence_reply="not json")
    chat_id = h.new_chat()
    done = next(d for e, d in h.send(chat_id, "latest box office") if e == "done")
    assert done["message"]["content"] == h.factory.model.reply
    assert done["message"]["confidence"] is None
    assert "<verified_notes>" not in system_texts(h.factory.model.calls[-1])[2]


def test_social_and_explicit_results_are_dropped(tmp_path: Path) -> None:
    searcher = FakeSearcher([
        SearchResult(title="ok", url="https://good.example.com/a", content="Normal news."),
        SearchResult(title="dup", url="https://good.example.com/a/", content="Same page again."),
        SearchResult(title="insta", url="https://www.instagram.com/p/xyz", content="Fan post with a number."),
        SearchResult(title="bad", url="https://www.xvideos.com/x", content="whatever"),
        SearchResult(title="flagged", url="https://other.example.com/b", content="EXPLICIT stuff"),
    ])
    h = Harness(tmp_path, searcher=searcher, router_intent="web_search")
    chat_id = h.new_chat()
    done = next(d for e, d in h.send(chat_id, "news please") if e == "done")
    assert [s["url"] for s in done["message"]["sources"]] == ["https://good.example.com/a"]


def test_all_results_explicit_gives_refusal(tmp_path: Path) -> None:
    searcher = FakeSearcher([SearchResult(title="x", url="https://a.example.com", content="EXPLICIT")])
    h = Harness(tmp_path, searcher=searcher, router_intent="web_search")
    chat_id = h.new_chat()
    events = h.send(chat_id, "find me something")
    replace = next(d for e, d in events if e == "replace")
    assert replace["status"] == "refused"
    assert h.factory.model.calls == []  # the answering model never saw the results
    assert h.factory.model.evidence_calls == []
    assert h.chat(chat_id)["messages"][-1]["status"] == "refused"


@pytest.mark.parametrize("searcher", [None, FakeSearcher(fail=True)])
def test_search_unavailable_answers_with_warning(tmp_path: Path, searcher) -> None:
    h = Harness(tmp_path, searcher=searcher, router_intent="web_search")
    chat_id = h.new_chat()
    done = next(d for e, d in h.send(chat_id, "latest news") if e == "done")
    assert done["message"]["sources"] == []
    assert any("Web search is unavailable" in s for s in system_texts(h.factory.model.calls[-1]))


def test_realtime_says_dont_know_without_any_llm_call(h: Harness) -> None:
    chat_id = h.new_chat()
    events = h.send(chat_id, "What's the weather in Kochi today?")
    replace = next(d for e, d in events if e == "replace")
    assert replace["text"].startswith("I don't know that yet")
    assert h.factory.model.calls == [] and h.factory.model.router_calls == []
    assert h.chat(chat_id)["messages"][-1]["content"].startswith("I don't know that yet")


def test_router_falls_back_to_rules_on_bad_output(tmp_path: Path) -> None:
    searcher = FakeSearcher()
    h = Harness(tmp_path, searcher=searcher, router_intent="nonsense")
    chat_id = h.new_chat()
    h.send(chat_id, "latest news about ISRO")
    assert searcher.queries == ["latest news about ISRO"]  # web_search via the rule fallback
    h.send(chat_id, "write a haiku about tea")
    assert len(searcher.queries) == 1  # chitchat


def test_router_sees_follow_up_context_and_cost_is_counted(h: Harness) -> None:
    chat_id = h.new_chat()
    h.send(chat_id, "Tell me about Kerala")
    h.send(chat_id, "and its capital?")
    router_prompt = h.factory.model.router_calls[-1]
    assert "Tell me about Kerala" in str(router_prompt[1].content)
    chat = h.chat(chat_id)
    answer_words = len(h.factory.model.reply.split(" "))
    router_words = len(json.dumps({"intent": "chitchat", "search_queries": []}).split(" "))
    per_call = lambda words: (60 * 0.10 + 40 * 0.01 + words * 0.50) / 1_000_000  # noqa: E731
    expected = 2 * per_call(answer_words) + 2 * per_call(router_words)
    assert abs(chat["total_cost_usd"] - expected) < 1e-9


def test_trivial_message_skips_router_llm(h: Harness) -> None:
    chat_id = h.new_chat()
    h.send(chat_id, "hello!")
    assert h.factory.model.router_calls == []


def test_date_and_time_questions_are_answered_not_refused(h: Harness) -> None:
    from app.graph.rules import is_datetime_question

    assert is_datetime_question("what is today's date and day, and what time is it for me?")
    assert is_datetime_question("What day is it today?")
    assert not is_datetime_question("what time does the shop open")
    chat_id = h.new_chat()
    events = h.send(chat_id, "what is today's date and what time is it?", timezone="Asia/Kolkata")
    assert not any(e == "replace" for e, _ in events)  # not the "don't know" reply
    assert h.factory.model.router_calls == []
    assert "Asia/Kolkata" in system_texts(h.factory.model.calls[-1])[0]


def test_invalid_timezone_falls_back_to_utc(h: Harness) -> None:
    chat_id = h.new_chat()
    h.send(chat_id, "hi", timezone="Mars/Olympus")
    assert "UTC" in system_texts(h.factory.model.calls[-1])[0]


# ---------------------------------------------------------------- uploads


def upload(h: Harness, chat_id: str, name: str, data: bytes, mime: str = "application/octet-stream"):
    return h.client.post(
        f"/api/chats/{chat_id}/attachments", files={"file": (name, data, mime)}, headers=h.headers
    )


def test_upload_document_and_image_reach_the_model(h: Harness) -> None:
    chat_id = h.new_chat()
    doc = upload(h, chat_id, "notes.txt", b"The secret code is 4242.", "text/plain")
    assert doc.status_code == 201, doc.text
    assert doc.json()["kind"] == "document" and doc.json()["text_chars"] == 24
    img = upload(h, chat_id, "pic.png", tiny_png(), "image/png")
    assert img.status_code == 201 and img.json()["kind"] == "image"

    ids = [doc.json()["id"], img.json()["id"]]
    events = h.send(chat_id, "What is in these files?", attachment_ids=ids)
    start = next(d for e, d in events if e == "start")
    assert [a["name"] for a in start["user_message"]["attachments"]] == ["notes.txt", "pic.png"]
    assert h.factory.model.router_calls == []  # files -> chitchat directly

    question = h.factory.model.calls[-1][-1]
    blocks = question.content
    assert isinstance(blocks, list)
    assert "The secret code is 4242." in blocks[0]["text"]
    assert blocks[0]["text"].endswith("What is in these files?")
    assert blocks[1]["image_url"]["url"].startswith("data:image/png;base64,")

    # Stored with the message; the file text itself is not copied into the chat JSON.
    saved_user = h.chat(chat_id)["messages"][0]
    assert len(saved_user["attachments"]) == 2
    assert "4242" not in saved_user["content"]

    # Download works with auth, and used files can't be deleted.
    got = h.client.get(f"/api/chats/{chat_id}/attachments/{ids[1]}", headers=h.headers)
    assert got.status_code == 200 and got.content == tiny_png()
    assert h.client.delete(f"/api/chats/{chat_id}/attachments/{ids[0]}", headers=h.headers).status_code == 409


def test_attachments_survive_restart(tmp_path: Path) -> None:
    first = Harness(tmp_path)
    chat_id = first.new_chat()
    doc = upload(first, chat_id, "a.md", b"# Plan\nShip phase 4 on Friday.").json()
    first.send(chat_id, "Summarise", attachment_ids=[doc["id"]])

    second = Harness(tmp_path)  # empty checkpointer -> seeded from JSON
    second.send(chat_id, "When do we ship?")
    first_human = second.factory.model.calls[-1][1]
    assert "Ship phase 4 on Friday." in str(first_human.content)


def test_docx_text_is_extracted(h: Harness) -> None:
    from docx import Document

    buf = io.BytesIO()
    document = Document()
    document.add_paragraph("Quarterly revenue grew 12%.")
    document.save(buf)
    chat_id = h.new_chat()
    res = upload(h, chat_id, "report.docx", buf.getvalue())
    assert res.status_code == 201, res.text
    h.send(chat_id, "", attachment_ids=[res.json()["id"]])  # file only, no text
    assert "Quarterly revenue grew 12%." in str(h.factory.model.calls[-1][-1].content)


def test_upload_limits_and_validation(tmp_path: Path) -> None:
    h = Harness(tmp_path, settings={"max_upload_mb": 1, "max_files_per_chat": 3})
    chat_id = h.new_chat()
    too_big = upload(h, chat_id, "big.txt", b"a" * (1024 * 1024 + 1))
    assert too_big.status_code == 413
    assert upload(h, chat_id, "virus.exe", b"MZ....").status_code == 415
    assert upload(h, chat_id, "fake.png", b"not really a png").status_code == 415
    assert upload(h, chat_id, "empty.txt", b"").status_code == 413

    ids = [upload(h, chat_id, f"f{i}.txt", b"hello").json()["id"] for i in range(3)]
    fourth = upload(h, chat_id, "f4.txt", b"hello")
    assert fourth.status_code == 413 and "at most 3 files" in fourth.json()["detail"]

    # Removing a not-yet-sent file frees a slot.
    assert h.client.delete(f"/api/chats/{chat_id}/attachments/{ids[0]}", headers=h.headers).status_code == 204
    assert upload(h, chat_id, "f4.txt", b"hello").status_code == 201

    bad = h.client.post(
        f"/api/chats/{chat_id}/messages",
        json={"content": "x", "attachment_ids": ["nope"]},
        headers=h.headers,
    )
    assert bad.status_code == 400
    other_chat = h.new_chat()
    assert h.client.get(f"/api/chats/{other_chat}/attachments/{ids[1]}", headers=h.headers).status_code == 404


def test_deleting_chat_removes_its_files(h: Harness) -> None:
    chat_id = h.new_chat()
    upload(h, chat_id, "a.txt", b"bye")
    folder = h.settings.data_dir / "users" / "u-tester" / "uploads" / chat_id
    assert folder.exists()
    h.client.delete(f"/api/chats/{chat_id}", headers=h.headers)
    assert not folder.exists()
