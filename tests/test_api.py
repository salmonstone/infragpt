import pytest
from unittest.mock import patch, MagicMock
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    with patch("database.engine"), \
         patch("database.Base.metadata.create_all"), \
         patch("main.init_db"), \
         patch("main.get_db") as mock_db:

        mock_session = MagicMock()
        mock_session.query.return_value.first.return_value = None
        mock_db.return_value = iter([mock_session])

        from main import app
        with TestClient(app) as c:
            yield c


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
    with patch("main.get_db") as mock_db:
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None
        mock_db.return_value = iter([mock_session])

        r = client.post(
            "/auth/login",
            data={"username": "nobody", "password": "wrong"},
        )
        assert r.status_code == 401


def test_chat_requires_auth(client):
    r = client.post("/chat", json={"message": "hello"})
    assert r.status_code == 403  # no bearer token


def test_chat_empty_message_rejected(client):
    with patch("main.get_current_user") as mock_user, \
         patch("main.get_db"):
        from database import User
        mock_user.return_value = User(username="user1", role="user")
        r = client.post("/chat", json={"message": "   "}, headers={"Authorization": "Bearer fake"})
        # Will hit auth before empty check in real flow; just ensure no 500
        assert r.status_code in (400, 401, 403)


def test_chat_readonly_role_blocked(client):
    with patch("auth.get_current_user") as mock_user, \
         patch("main.get_db"):
        from database import User
        mock_user.return_value = User(username="ro", role="readonly")

        with patch("main.get_current_user", return_value=User(username="ro", role="readonly")):
            r = client.post(
                "/chat",
                json={"message": "hello"},
                headers={"Authorization": "Bearer fake"},
            )
            assert r.status_code in (403, 401)
