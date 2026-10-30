"""Things that matter once the game runs on a real server with lots of players."""

import pytest
from sqlalchemy import text

from mafia_hustle import create_app
from mafia_hustle.extensions import db, limiter
from mafia_hustle.game import random_other_player


@pytest.fixture
def make_app(tmp_path):
    apps = []

    def make(**config):
        app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'game.db'}",
                "WTF_CSRF_ENABLED": False,
                **config,
            }
        )
        apps.append(app)
        with app.app_context():
            limiter.reset()
        return app

    yield make
    for app in apps:
        with app.app_context():
            db.engine.dispose()


def test_random_other_player_never_picks_yourself(make_user):
    me = make_user("vito")
    assert random_other_player(me) is None

    others = {make_user(name).id for name in ("sonny", "fredo", "michael")}
    picked = {random_other_player(me).id for _ in range(200)}
    assert picked == others


def test_sqlite_uses_wal_and_waits_for_locks(make_app):
    with make_app().app_context():
        assert db.session.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert db.session.execute(text("PRAGMA busy_timeout")).scalar() == 5000


def test_instance_path_comes_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path / "data"))
    app = create_app({"SECRET_KEY": "x", "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    assert app.instance_path == str(tmp_path / "data")
    assert (tmp_path / "data").is_dir()
    with app.app_context():
        db.engine.dispose()


def test_game_actions_are_rate_limited(make_app):
    app = make_app()
    client = app.test_client()
    with app.app_context():
        from mafia_hustle.models import User

        user = User(provider="fediverse", subject="t:1", username="vito")
        db.session.add(user)
        db.session.commit()
        with client.session_transaction() as session:
            session["_user_id"] = str(user.id)

    codes = [client.post("/api/heal-up").status_code for _ in range(3)]
    assert codes[:2] == [200, 200]
    assert codes[2] == 429
    assert "Slow down" in client.post("/api/heal-up").get_json()["error"]


def test_login_attempts_are_rate_limited_per_ip(make_app):
    client = make_app().test_client()
    for _ in range(10):
        assert client.post("/login/fediverse", data={"instance": "nope"}).status_code == 302
    response = client.post("/login/fediverse", data={"instance": "nope"}, follow_redirects=True)
    assert b"Too many attempts" in response.data


def test_behind_a_proxy_each_player_ip_gets_its_own_limit(make_app):
    client = make_app(TRUST_PROXY=1).test_client()

    def attempt(ip):
        response = client.post(
            "/login/fediverse",
            data={"instance": "nope"},
            headers={"X-Forwarded-For": ip},
            follow_redirects=True,
        )
        return b"Too many attempts" in response.data

    assert not any(attempt("1.1.1.1") for _ in range(10))
    assert attempt("1.1.1.1")
    assert not attempt("2.2.2.2")
