import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.security import hash_password  # noqa: E402

TEST_PASSWORD = "correct-horse-battery"
TEST_SECRET = "test-secret-" + "x" * 40

# app.main builds a module-level app on import; give it valid config.
os.environ.setdefault("JWT_SECRET", TEST_SECRET)
os.environ.setdefault("APP_PASSWORD_HASH", hash_password(TEST_PASSWORD))
os.environ.setdefault("STORAGE_BACKEND", "memory")

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


def make_settings(tmp_path: Path, storage: str, **overrides) -> Settings:
    values = dict(
        _env_file=None,
        environment="test",
        app_username="tester",
        app_display_name="Tester",
        app_password_hash=hash_password(TEST_PASSWORD),
        jwt_secret=TEST_SECRET,
        storage_backend=storage,
        data_dir=tmp_path / "data",
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(params=["json", "memory"])
def client(request: pytest.FixtureRequest, tmp_path: Path) -> TestClient:
    return TestClient(create_app(make_settings(tmp_path, request.param)))


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    res = client.post("/api/auth/login", json={"username": "tester", "password": TEST_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}
