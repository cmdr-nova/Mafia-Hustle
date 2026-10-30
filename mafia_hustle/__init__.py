import os

from flask import (
    Flask,
    current_app,
    flash,
    jsonify,
    redirect,
    request,
    send_from_directory,
    url_for,
)
from sqlalchemy import event
from werkzeug.middleware.proxy_fix import ProxyFix

from .extensions import csrf, db, limiter, login_manager
from .models import User, upgrade_schema


def create_app(test_config=None):
    # INSTANCE_PATH is where the SQLite database lives. Defaults to ./instance next to the code;
    # the production setup points it at /var/lib/mafia-hustle so the code folder stays read-only.
    app = Flask(
        __name__, instance_path=os.environ.get("INSTANCE_PATH"), instance_relative_config=True
    )

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///mafia_hustle.db"),
        # Where the game lives on the internet, e.g. https://hustle.example.com. Needed for
        # Bluesky logins in production. Leave unset for local development.
        PUBLIC_URL=os.environ.get("PUBLIC_URL"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # How many reverse proxies sit in front of the app (1 behind Caddy or nginx). Lets the
        # rate limiter see each player's real IP instead of the proxy's.
        TRUST_PROXY=int(os.environ.get("TRUST_PROXY", "0")),
        # Spelled out because the limiter otherwise remembers the last app's setting.
        RATELIMIT_ENABLED=True,
        # Adds a page that logs you in as any bot, no OAuth needed. For local testing only;
        # the app refuses to start with it on a public https address.
        DEV_LOGIN=os.environ.get("DEV_LOGIN") == "1",
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

    if app.config["DEV_LOGIN"] and (app.config.get("PUBLIC_URL") or "").startswith("https://"):
        raise RuntimeError("DEV_LOGIN lets anyone log in as a bot. Never use it in production.")

    if app.config["TRUST_PROXY"]:
        n = app.config["TRUST_PROXY"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n)

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    from . import bots
    from .auth import bp as auth_bp
    from .game import bp as game_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(game_bp)
    app.cli.add_command(bots.cli)
    if app.config["DEV_LOGIN"]:
        app.register_blueprint(bots.dev_bp)

    @app.get("/favicon.ico")
    def favicon():
        return send_from_directory(app.static_folder, "favicon.svg", mimetype="image/svg+xml")

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.errorhandler(429)
    def too_many_requests(_error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Slow down, wise guy. Try again in a second."}), 429
        flash("Too many attempts. Wait a minute and try again.", "warning")
        return redirect(url_for("auth.login"))

    with app.app_context():
        if db.engine.dialect.name == "sqlite":
            event.listen(db.engine, "connect", tune_sqlite)
        db.create_all()
        upgrade_schema()

    return app


def tune_sqlite(dbapi_connection, _record):
    """WAL lets reads happen while a write is in progress, and busy_timeout makes a writer wait
    its turn instead of failing with "database is locked" when several workers write at once."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


@login_manager.user_loader
def load_user(user_id):
    user = db.session.get(User, int(user_id))
    # Bots are played by the server. Nobody gets to log in as one (outside DEV_LOGIN).
    if user is not None and user.is_bot and not current_app.config["DEV_LOGIN"]:
        return None
    return user
