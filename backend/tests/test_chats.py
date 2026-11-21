from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import TEST_PASSWORD, make_settings


def test_chat_crud(client: TestClient, auth_headers: dict[str, str]) -> None:
    assert client.get("/api/chats", headers=auth_headers).json() == []

    first = client.post("/api/chats", json={}, headers=auth_headers).json()
    second = client.post("/api/chats", json={"title": "Plans"}, headers=auth_headers).json()
    assert first["title"] == "New chat"

    listed = client.get("/api/chats", headers=auth_headers).json()
    assert [c["id"] for c in listed] == [second["id"], first["id"]]  # newest first

    renamed = client.patch(
        f"/api/chats/{first['id']}", json={"title": "Renamed"}, headers=auth_headers
    ).json()
    assert renamed["title"] == "Renamed"
    # Renaming bumps updated_at, so it moves to the top.
    assert client.get("/api/chats", headers=auth_headers).json()[0]["id"] == first["id"]

    detail = client.get(f"/api/chats/{first['id']}", headers=auth_headers).json()
    assert detail["messages"] == []

    assert client.delete(f"/api/chats/{first['id']}", headers=auth_headers).status_code == 204
    assert client.get(f"/api/chats/{first['id']}", headers=auth_headers).status_code == 404
    assert len(client.get("/api/chats", headers=auth_headers).json()) == 1


def test_unknown_and_malicious_ids(client: TestClient, auth_headers: dict[str, str]) -> None:
    assert client.get("/api/chats/doesnotexist", headers=auth_headers).status_code == 404
    assert client.get("/api/chats/..%2F..%2Fsecret", headers=auth_headers).status_code == 404
    assert client.delete("/api/chats/nope", headers=auth_headers).status_code == 404


def test_rename_rejects_blank_title(client: TestClient, auth_headers: dict[str, str]) -> None:
    chat = client.post("/api/chats", json={}, headers=auth_headers).json()
    res = client.patch(f"/api/chats/{chat['id']}", json={"title": "   "}, headers=auth_headers)
    assert res.status_code == 422


def test_json_storage_survives_restart(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, "json")
    login = {"username": "tester", "password": TEST_PASSWORD}

    c1 = TestClient(create_app(settings))
    token = c1.post("/api/auth/login", json=login).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    created = c1.post("/api/chats", json={"title": "Keep me"}, headers=headers).json()

    # A brand-new app instance (simulates a backend restart) reads the same files.
    c2 = TestClient(create_app(settings))
    titles = [c["title"] for c in c2.get("/api/chats", headers=headers).json()]
    assert titles == ["Keep me"]

    # Corrupt index is rebuilt from the chat files.
    index = tmp_path / "data" / "users" / "u-tester" / "chats" / "index.json"
    index.write_text("{ broken", encoding="utf-8")
    ids = [c["id"] for c in c2.get("/api/chats", headers=headers).json()]
    assert ids == [created["id"]]
