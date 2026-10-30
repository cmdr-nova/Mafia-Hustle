"""The live game has a database from before 0.3. Starting the new code must upgrade it in place
without losing anyone."""

import sqlite3

from mafia_hustle import create_app
from mafia_hustle.extensions import db
from mafia_hustle.models import User

OLD_USER_TABLE = """
CREATE TABLE user (
    id INTEGER NOT NULL PRIMARY KEY,
    provider VARCHAR(16) NOT NULL,
    subject VARCHAR(300) NOT NULL,
    username VARCHAR(300) NOT NULL,
    display_name VARCHAR(200),
    avatar_url VARCHAR(500),
    created_at DATETIME NOT NULL,
    health INTEGER NOT NULL,
    money INTEGER NOT NULL,
    level INTEGER NOT NULL,
    points INTEGER NOT NULL,
    kills INTEGER NOT NULL,
    prestige INTEGER NOT NULL,
    UNIQUE (provider, subject)
)
"""


def test_old_database_is_upgraded_in_place(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute(OLD_USER_TABLE)
    old.execute(
        "INSERT INTO user VALUES (1, 'bluesky', 'did:plc:x', 'vito.bsky.social', NULL, NULL,"
        " '2026-10-29 10:00:00', 40, 2500, 3, 12, 2, 0)"
    )
    old.commit()
    old.close()

    config = {
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{path}",
        "WTF_CSRF_ENABLED": False,
    }
    for _ in range(2):  # a second start (or a second worker) finds nothing to do
        app = create_app(config)
        with app.app_context():
            vito = db.session.get(User, 1)
            assert (vito.username, vito.money, vito.kills) == ("vito.bsky.social", 2500, 2)
            assert (vito.energy, vito.max_energy, vito.attack, vito.bank) == (20, 20, 5, 0)
            assert vito.skill_points == 6  # 3 per level they already earned
            assert vito.energy_at is None
            db.engine.dispose()

    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = "1"
    assert client.get("/api/state").get_json()["player"]["skill_points"] == 6
    with app.app_context():
        db.engine.dispose()
