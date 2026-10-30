from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
csrf = CSRFProtect()
login_manager = LoginManager()


def player_or_ip():
    """Rate-limit logged-in players by account, everyone else by IP address."""
    if current_user.is_authenticated:
        return f"player:{current_user.id}"
    return get_remote_address()


# In-memory counters are per gunicorn worker, so the real limit is roughly limit x workers.
# That's fine for stopping autoclickers. Point RATELIMIT_STORAGE_URI at Redis for exact limits.
limiter = Limiter(key_func=player_or_ip, storage_uri="memory://")
