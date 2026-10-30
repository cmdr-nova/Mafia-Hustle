from datetime import UTC, datetime

from flask_login import UserMixin
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    inspect,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .extensions import db


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


def stat(default):
    """An integer stat column. server_default lets upgrade_schema() add it to an existing
    database, where every player already in the table gets `default`."""
    return mapped_column(default=default, server_default=text(str(default)))


class User(db.Model, UserMixin):
    """A player. There are no passwords: players sign in with a fediverse or Bluesky account,
    and we only keep who they are on that network (provider + subject)."""

    __table_args__ = (UniqueConstraint("provider", "subject"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # "fediverse", "bluesky", or "bot" (computer players, see bots.py; they can never log in)
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

    # Added in 0.3. Every column from here down needs a server_default (see stat()) or to be
    # nullable, so upgrade_schema() can add it to the live database.
    bank: Mapped[int] = stat(0)
    energy: Mapped[int] = stat(20)
    stamina: Mapped[int] = stat(10)
    max_energy: Mapped[int] = stat(20)
    max_stamina: Mapped[int] = stat(10)
    attack: Mapped[int] = stat(5)
    defense: Mapped[int] = stat(5)
    health_bonus: Mapped[int] = stat(0)
    skill_points: Mapped[int] = stat(0)
    jobs_done: Mapped[int] = stat(0)
    fights_won: Mapped[int] = stat(0)
    fights_lost: Mapped[int] = stat(0)
    # When each bar last ticked up. None means "start counting now".
    energy_at: Mapped[datetime | None] = mapped_column(DateTime)
    stamina_at: Mapped[datetime | None] = mapped_column(DateTime)
    health_at: Mapped[datetime | None] = mapped_column(DateTime)
    # When racket income was last collected.
    income_at: Mapped[datetime | None] = mapped_column(DateTime)

    @property
    def is_bot(self):
        return self.provider == "bot"


class Holding(db.Model):
    """Something a player owns from the shop: gear (quantity 1) or rackets (any quantity).
    `item` is a key from catalog.py."""

    __table_args__ = (UniqueConstraint("user_id", "item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    item: Mapped[str] = mapped_column(String(40))
    quantity: Mapped[int] = mapped_column(default=1)


class Event(db.Model):
    """Something that happened to a player while they weren't looking, like getting jumped.
    Shown on "The Wire". Only the newest few per player are kept."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


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


# Run once, right after a column is added, to give existing rows a sensible value.
BACKFILL = {
    # Players who levelled up before skills existed get the points they would have earned.
    ("user", "skill_points"): "UPDATE user SET skill_points = 3 * (level - 1)",
}


def upgrade_schema():
    """Add any columns the models have but the database doesn't.

    db.create_all() makes missing tables but never changes existing ones, so without this a new
    column would crash the live game. It only ever adds columns, which is all the game has
    needed so far. Several gunicorn workers may run this at once; whoever loses the race sees
    the column already there and moves on.
    """
    engine = db.engine
    for table in db.metadata.sorted_tables:
        existing = {c["name"] for c in inspect(engine).get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            if column.server_default is None and not column.nullable:
                raise RuntimeError(
                    f"{table.name}.{column.name} needs a server_default to be added to an "
                    "existing database."
                )
            ddl = f"ALTER TABLE {table.name} ADD COLUMN {column.name} "
            ddl += column.type.compile(engine.dialect)
            if column.server_default is not None:
                ddl += f" NOT NULL DEFAULT {column.server_default.arg.text}"
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                    if (table.name, column.name) in BACKFILL:
                        conn.execute(text(BACKFILL[table.name, column.name]))
            except Exception:
                existing = {c["name"] for c in inspect(engine).get_columns(table.name)}
                if column.name not in existing:
                    raise
