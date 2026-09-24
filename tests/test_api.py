import pytest
from unittest.mock import patch, MagicMock
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi.testclient import TestClient
from database import get_db, User
from auth import get_current_user


@pytest.fixture(scope="module")
def client():
    with patch("database.engine"), \
         patch("database.Base.metadata.create_all"), \
         patch("main.init_db"), \
         patch("main.get_db") as mock_startup_get_db:

        # Startup (lifespan) calls get_db() directly as a plain generator,
        # not through FastAPI's DI — pretend a user already exists so the
        # seed-admin step is skipped during tests.
        startup_session = MagicMock()
        startup_session.query.return_value.first.return_value = MagicMock()
        mock_startup_get_db.return_value = iter([startup_session])

        from main import app
        with TestClient(app) as c:
            yield c

        app.dependency_overrides.clear()


def _override_db(session):
    """Route handlers use `Depends(get_db)`, which FastAPI binds to the real
    `get_db` function object at decoration time — `patch("main.get_db")`
    only rebinds the *name*, so it never reaches an already-registered route.
    `app.dependency_overrides` is the mechanism FastAPI provides for this.
    The override must itself be a generator function (like `get_db`) so
    FastAPI applies its yield-dependency handling instead of treating the
    return value as the dependency's value directly."""
    from main import app

    def _fake_get_db():
        yield session

    app.dependency_overrides[get_db] = _fake_get_db


def _override_user(user):
    from main import app
    app.dependency_overrides[get_current_user] = lambda: user


def _clear_overrides(*deps):
    from main import app
    for dep in deps:
        app.dependency_overrides.pop(dep, None)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "healthy"
    assert data["service"] == "InfraGPT"
    assert "timestamp" in data


def test_metrics_endpoint(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "infragpt" in r.text


def test_login_missing_body(client):
    r = client.post("/auth/login")
    assert r.status_code == 422  # unprocessable entity


def test_login_wrong_credentials(client):
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = None
    _override_db(mock_session)
    try:
        r = client.post(
            "/auth/login",
            data={"username": "nobody", "password": "wrong"},
        )
        assert r.status_code == 401
    finally:
        _clear_overrides(get_db)


def test_chat_requires_auth(client):
    r = client.post("/chat", json={"message": "hello"})
    assert r.status_code == 403  # no bearer token at all


def test_chat_empty_message_rejected(client):
    _override_user(User(username="user1", role="user"))
    try:
        r = client.post("/chat", json={"message": "   "}, headers={"Authorization": "Bearer fake"})
        assert r.status_code == 400
        assert r.json()["detail"] == "Empty message"
    finally:
        _clear_overrides(get_current_user)


def test_chat_readonly_role_blocked(client):
    _override_user(User(username="ro", role="readonly"))
    try:
        r = client.post(
            "/chat",
            json={"message": "hello"},
            headers={"Authorization": "Bearer fake"},
        )
        assert r.status_code == 403
        assert "Read-only" in r.json()["detail"]
    finally:
        _clear_overrides(get_current_user)
