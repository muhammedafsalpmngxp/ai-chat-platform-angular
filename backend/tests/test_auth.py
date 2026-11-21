from fastapi.testclient import TestClient

from tests.conftest import TEST_PASSWORD


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"


def test_login_success_and_me(client: TestClient, auth_headers: dict[str, str]) -> None:
    res = client.get("/api/auth/me", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["username"] == "tester"


def test_login_is_case_insensitive_on_username(client: TestClient) -> None:
    res = client.post("/api/auth/login", json={"username": "Tester", "password": TEST_PASSWORD})
    assert res.status_code == 200


def test_login_wrong_password(client: TestClient) -> None:
    res = client.post("/api/auth/login", json={"username": "tester", "password": "nope"})
    assert res.status_code == 401


def test_protected_routes_need_token(client: TestClient) -> None:
    assert client.get("/api/chats").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_models_catalog(client: TestClient, auth_headers: dict[str, str]) -> None:
    catalog = client.get("/api/models", headers=auth_headers).json()
    assert catalog["default_model"] == "gpt-6-luna"
    assert catalog["prices_as_of"] == "2026-11-20"
    assert catalog["premium_unlock_minutes"] == 30
    models = {m["id"]: m for m in catalog["models"]}
    assert [i for i, m in models.items() if m["is_default"]] == ["gpt-6-luna"]
    assert models["gpt-6.2-astra"]["requires_reauth"] is True
    assert models["gpt-6.2-astra"]["relative_cost"] == 80.0
    assert models["gpt-6-luna"]["relative_cost"] == 1.0
    assert models["gpt-5.6-luna"]["tier"] == "low"


def test_reauth_issues_unlock_token(client: TestClient, auth_headers: dict[str, str]) -> None:
    res = client.post("/api/auth/reauth", json={"password": TEST_PASSWORD}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["expires_in"] == 30 * 60
    wrong = client.post("/api/auth/reauth", json={"password": "nope"}, headers=auth_headers)
    assert wrong.status_code == 403  # session stays valid
    assert client.post("/api/auth/reauth", json={"password": TEST_PASSWORD}).status_code == 401


def test_password_lockout_after_repeated_failures(client: TestClient, auth_headers: dict[str, str]) -> None:
    for _ in range(5):
        res = client.post("/api/auth/reauth", json={"password": "bad"}, headers=auth_headers)
        assert res.status_code == 403
    locked = client.post("/api/auth/reauth", json={"password": TEST_PASSWORD}, headers=auth_headers)
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0

    for _ in range(5):
        client.post("/api/auth/login", json={"username": "tester", "password": "bad"})
    login = client.post("/api/auth/login", json={"username": "tester", "password": TEST_PASSWORD})
    assert login.status_code == 429


def test_cost_maths() -> None:
    from pathlib import Path

    from app.core.models_catalog import load_catalog

    catalog = load_catalog(Path(__file__).resolve().parents[1] / "config" / "models.yaml")
    # Luna: $0.10 in / $0.01 cached / $0.50 out per 1M.
    cost = catalog.cost_usd("gpt-6-luna", input_tokens=1_000_000, output_tokens=1_000_000, cached_input_tokens=500_000)
    assert round(cost, 6) == round(0.05 + 0.005 + 0.50, 6)
    assert catalog.cost_usd("unknown", 10, 10) == 0.0
