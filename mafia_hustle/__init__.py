import os

from flask import Flask

from .extensions import csrf, db, login_manager
from .models import User


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///mafia_hustle.db"),
        # Where the game lives on the internet, e.g. https://hustle.example.com. Needed for
        # Bluesky logins in production. Leave unset for local development.
        PUBLIC_URL=os.environ.get("PUBLIC_URL"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)
    if (app.config.get("PUBLIC_URL") or "").startswith("https://"):
        app.config["SESSION_COOKIE_SECURE"] = True

    # Flask signs the login cookie with this key. A guessable key means anyone can forge a
    # cookie and log in as any player, so refuse to start without a real one.
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError(
            "SECRET_KEY is not set. Copy .env.example to .env and generate one with:\n"
            "  python -c 'import secrets; print(secrets.token_hex())'"
        )

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    from .auth import bp as auth_bp
    from .game import bp as game_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(game_bp)

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    with app.app_context():
        db.create_all()

    return app


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
