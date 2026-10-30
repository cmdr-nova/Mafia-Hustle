from datetime import UTC, datetime

from flask_login import UserMixin
from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .extensions import db


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


class User(db.Model, UserMixin):
    """A player. There are no passwords: players sign in with a fediverse or Bluesky account,
    and we only keep who they are on that network (provider + subject)."""

    __table_args__ = (UniqueConstraint("provider", "subject"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # "fediverse" or "bluesky"
    provider: Mapped[str] = mapped_column(String(16))
    # Stable account id on that network: "<instance>:<account id>" or a DID. Handles can change,
    # so this is what we match on when someone logs in again.
    subject: Mapped[str] = mapped_column(String(300))
    # Shown in the game, e.g. "@vito@fedi.example.org" or "vito.bsky.social". Refreshed every login.
    username: Mapped[str] = mapped_column(String(300))
    display_name: Mapped[str | None] = mapped_column(String(200))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    health: Mapped[int] = mapped_column(default=100)
    money: Mapped[int] = mapped_column(default=1000)
    level: Mapped[int] = mapped_column(default=1)
    points: Mapped[int] = mapped_column(default=0)
    kills: Mapped[int] = mapped_column(default=0)
    prestige: Mapped[int] = mapped_column(default=0)


class FediverseApp(db.Model):
    """OAuth app credentials we registered on a fediverse instance. Mastodon-API servers
    (Mastodon, GoToSocial, Akkoma, ...) hand these out per instance, so we register once and
    reuse them."""

    domain: Mapped[str] = mapped_column(String(253), primary_key=True)
    redirect_uri: Mapped[str] = mapped_column(String(500))
    client_id: Mapped[str] = mapped_column(String(200))
    client_secret: Mapped[str] = mapped_column(String(200))


class PendingLogin(db.Model):
    """A login that went off to the player's server and hasn't come back yet. Deleted as soon
    as the callback arrives, or after a few minutes."""

    state: Mapped[str] = mapped_column(String(100), primary_key=True)
    provider: Mapped[str] = mapped_column(String(16))
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
