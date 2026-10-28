import pytest

from mafia_hustle import create_app
from mafia_hustle.extensions import db
from mafia_hustle.models import User


@pytest.fixture
def app():
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        }
    )
    with app.app_context():
        yield app
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_user(app):
    def make(username, **stats):
        user = User(provider="fediverse", subject=f"test:{username}", username=username, **stats)
        db.session.add(user)
        db.session.commit()
        return user

    return make


@pytest.fixture
def login(client):
    def do_login(user):
        with client.session_transaction() as session:
            session["_user_id"] = str(user.id)
            session["_fresh"] = True

    return do_login
