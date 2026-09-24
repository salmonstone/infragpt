import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
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


# ---------- registration ----------

def test_register_success(client):
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = None  # username free
    _override_db(mock_session)
    try:
        r = client.post("/auth/register", json={"username": "alice", "password": "alicepass123"})
        assert r.status_code == 201
        body = r.json()
        assert body["role"] == "user"  # role is never client-settable, always "user"
        assert "access_token" in body
    finally:
        _clear_overrides(get_db)


def test_register_duplicate_username(client):
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = User(username="alice", role="user")
    _override_db(mock_session)
    try:
        r = client.post("/auth/register", json={"username": "alice", "password": "alicepass123"})
        assert r.status_code == 409
    finally:
        _clear_overrides(get_db)


def test_register_weak_password_rejected(client):
    r = client.post("/auth/register", json={"username": "bob", "password": "ab"})
    assert r.status_code == 422  # min_length=6, no DB hit needed


# ---------- admin: users ----------

def test_admin_list_users_forbidden_for_non_admin(client):
    _override_user(User(username="alice", role="user"))
    try:
        r = client.get("/admin/users", headers={"Authorization": "Bearer fake"})
        assert r.status_code == 403
    finally:
        _clear_overrides(get_current_user)


def test_admin_list_users_success(client):
    _override_user(User(username="admin", role="admin"))
    mock_session = MagicMock()
    mock_session.query.return_value.order_by.return_value.all.return_value = [
        User(username="admin", role="admin", created_at=datetime(2026, 1, 1)),
        User(username="alice", role="user", created_at=datetime(2026, 1, 2)),
    ]
    _override_db(mock_session)
    try:
        r = client.get("/admin/users", headers={"Authorization": "Bearer fake"})
        assert r.status_code == 200
        usernames = [u["username"] for u in r.json()]
        assert usernames == ["admin", "alice"]
    finally:
        _clear_overrides(get_current_user, get_db)


def test_admin_user_history_not_found(client):
    _override_user(User(username="admin", role="admin"))
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = None  # no such user
    _override_db(mock_session)
    try:
        r = client.get("/admin/users/ghost/history", headers={"Authorization": "Bearer fake"})
        assert r.status_code == 404
    finally:
        _clear_overrides(get_current_user, get_db)


def test_history_requires_auth(client):
    r = client.get("/history")
    assert r.status_code == 403  # no bearer token


# ---------- admin: role management ----------

def test_role_update_forbidden_for_non_admin(client):
    _override_user(User(username="alice", role="user"))
    try:
        r = client.patch(
            "/admin/users/alice/role",
            json={"role": "admin"},
            headers={"Authorization": "Bearer fake"},
        )
        assert r.status_code == 403
    finally:
        _clear_overrides(get_current_user)


def test_role_update_invalid_role_rejected(client):
    _override_user(User(username="admin", role="admin"))
    try:
        r = client.patch(
            "/admin/users/alice/role",
            json={"role": "superuser"},
            headers={"Authorization": "Bearer fake"},
        )
        assert r.status_code == 422  # doesn't match the admin|user|readonly pattern
    finally:
        _clear_overrides(get_current_user)


def test_role_update_cannot_demote_last_admin(client):
    _override_user(User(username="admin", role="admin"))
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = User(username="admin", role="admin")
    mock_session.query.return_value.filter.return_value.count.return_value = 0  # no other admins left
    _override_db(mock_session)
    try:
        r = client.patch(
            "/admin/users/admin/role",
            json={"role": "user"},
            headers={"Authorization": "Bearer fake"},
        )
        assert r.status_code == 400
        assert "last remaining admin" in r.json()["detail"]
    finally:
        _clear_overrides(get_current_user, get_db)

# Note: the /chat DB-first-lookup and conversation-context logic (skip the AI
# for an exact repeat question; pass recent turns as context otherwise) is
# deliberately not unit-tested here with mocks — db.query(ChatHistory) is
# called twice per request with different filters, and a generic MagicMock
# can't distinguish those calls without fragile, over-specified setup that
# would mostly test the mock rather than the logic. That logic was instead
# verified against a real SQLite DB and a real Groq call: an exact-repeat
# question returned the saved answer with zero additional LLM calls, and a
# context-dependent follow-up ("what's my favorite AWS service?") answered
# correctly using an earlier message — see project history for the transcript.
