import pytest

from mafia_hustle import create_app
from mafia_hustle.extensions import db
from mafia_hustle.models import Event, Holding, User


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


def bots():
    return db.session.scalars(db.select(User).where(User.provider == "bot")).all()


def test_add_is_safe_to_run_twice(runner):
    assert "Added" in runner.invoke(args=["bots", "add", "--count", "3"]).output
    runner.invoke(args=["bots", "add", "--count", "3"])
    assert len(bots()) == 3


def test_bots_play_the_game(runner, make_user):
    human = make_user("vito")
    runner.invoke(args=["bots", "add"])
    result = runner.invoke(args=["bots", "tick"])
    assert result.exit_code == 0, result.output
    db.session.expire_all()
    assert sum(b.jobs_done for b in bots()) > 0
    assert sum(b.fights_won + b.fights_lost for b in bots()) > 0
    assert human.health >= 0
    assert "lvl" in runner.invoke(args=["bots", "list"]).output


def test_remove_cleans_up_everything(runner, make_user):
    human = make_user("vito")
    runner.invoke(args=["bots", "add"])
    for _ in range(3):
        runner.invoke(args=["bots", "tick", "--quiet"])
    runner.invoke(args=["bots", "remove"])
    assert bots() == []
    owners = set(db.session.scalars(db.select(Holding.user_id))) | set(
        db.session.scalars(db.select(Event.user_id))
    )
    assert owners <= {human.id}


def test_nobody_can_log_in_as_a_bot(client, runner):
    runner.invoke(args=["bots", "add", "--count", "1"])
    with client.session_transaction() as session:
        session["_user_id"] = str(bots()[0].id)
    assert client.get("/api/state").status_code == 302
    assert client.get("/dev/login").status_code == 404


def test_dev_login():
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "DEV_LOGIN": True,
        }
    )
    with app.app_context():
        app.test_cli_runner().invoke(args=["bots", "add", "--count", "1"])
        bot_id = bots()[0].id
        client = app.test_client()
        assert b"Knuckles" in client.get("/dev/login").data
        assert client.post(f"/dev/login/{bot_id}").status_code == 302
        assert client.get("/api/state").get_json()["player"]["id"] == bot_id
        db.session.remove()
        db.engine.dispose()


def test_dev_login_refuses_to_run_in_production():
    with pytest.raises(RuntimeError, match="DEV_LOGIN"):
        create_app(
            {
                "SECRET_KEY": "x",
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "DEV_LOGIN": True,
                "PUBLIC_URL": "https://hustle.example.com",
            }
        )


def test_bots_retire_past_the_level_cap(runner):
    from mafia_hustle import bots as bots_module

    runner.invoke(args=["bots", "add", "--count", "2"])
    veteran, rookie = bots()
    veteran.level, veteran.kills = bots_module.MAX_LEVEL + 1, 7
    db.session.add(Holding(user_id=veteran.id, item="knuckles", quantity=1))
    db.session.commit()
    old_id, subject, rookie_name = veteran.id, veteran.subject, rookie.username

    output = runner.invoke(args=["bots", "tick"]).output
    assert "Retired" in output
    db.session.expire_all()
    crew = {b.subject: b for b in bots()}
    assert len(crew) == 2
    replacement = crew[subject]
    assert replacement.username != "Knuckles Malone"
    assert replacement.level <= 2 and replacement.kills == 0
    assert db.session.scalar(db.select(Holding).where(Holding.user_id == old_id)) is None
    assert crew[rookie.subject].username == rookie_name  # bots under the cap are left alone


def test_bots_leave_much_weaker_people_alone(runner, make_user):
    newbie = make_user("newbie")
    runner.invoke(args=["bots", "add", "--count", "1"])
    bot = bots()[0]
    bot.level = 4
    db.session.commit()
    for _ in range(5):
        bot.stamina, bot.health = 10, 200
        db.session.commit()
        runner.invoke(args=["bots", "tick", "--quiet"])
    db.session.expire_all()
    assert newbie.fights_won + newbie.fights_lost == 0
