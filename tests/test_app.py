import pytest

from mafia_hustle import create_app
from mafia_hustle.extensions import db


def test_refuses_to_start_without_secret_key(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})


def test_security_headers(client):
    response = client.get("/login")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_game_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_csrf_is_enforced():
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        }
    )
    response = app.test_client().post("/api/do/hospital")
    assert response.status_code == 400
    with app.app_context():
        db.engine.dispose()
