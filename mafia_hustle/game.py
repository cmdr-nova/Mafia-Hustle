import random
import re

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from . import rules
from .catalog import GEAR, GEAR_BY_KEY, JOBS, JOBS_BY_KEY, RACKETS, RACKETS_BY_KEY
from .extensions import db, limiter
from .models import Event, Holding, User, utcnow

bp = Blueprint("game", __name__)

# Plenty for a human clicking, not enough for a script hammering the server.
ACTION_LIMIT = "2 per second;60 per minute"
EVENTS_KEPT = 30
EVENTS_SHOWN = 15
TARGETS_SHOWN = 8
LEADERBOARD_SIZE = 10


# --- Pages and read-only API -------------------------------------------------------------------


@bp.route("/")
@login_required
def index():
    return render_template(
        "index.html",
        profile_url=profile_url(current_user),
        network=NETWORK_NAMES.get(current_user.provider, current_user.provider),
    )


NETWORK_NAMES = {"fediverse": "Fediverse", "bluesky": "Bluesky", "bot": "Bot"}
HANDLE_PART = re.compile(r"[A-Za-z0-9._-]+")


def profile_url(user):
    """Link to the player's own profile on their network, or None if we can't build a safe one.
    Fediverse handles look like @name@instance, Bluesky handles like name.bsky.social."""
    if user.provider == "fediverse":
        name, _, domain = user.username.lstrip("@").partition("@")
        if HANDLE_PART.fullmatch(name) and HANDLE_PART.fullmatch(domain) and "." in domain:
            return f"https://{domain}/@{name}"
    elif user.provider == "bluesky" and HANDLE_PART.fullmatch(user.username):
        return f"https://bsky.app/profile/{user.username}"
    return None


@bp.get("/api/state")
@login_required
def state():
    # Regenerating writes to the player, so this takes the write lock like any action.
    player = locked_player()
    now = utcnow()
    rules.regenerate(player, now)
    holdings = load_holdings(player)
    db.session.commit()
    return jsonify(player_state(player, holdings, now))


@bp.get("/api/targets")
@login_required
def targets():
    return jsonify({"targets": [public_player(u) for u in find_targets(current_user)]})


@bp.get("/api/leaderboard")
def leaderboard():
    top = db.session.scalars(
        db.select(User)
        .order_by(User.kills.desc(), User.level.desc(), User.points.desc())
        .limit(LEADERBOARD_SIZE)
    ).all()
    # Logged-in players outside the top 10 also get their own spot, for the pinned row.
    me = None
    if current_user.is_authenticated and current_user.id not in {u.id for u in top}:
        me = {**public_player(current_user), "rank": rank_of(current_user)}
    return jsonify({"leaderboard": [public_player(u) for u in top], "me": me})


def rank_of(user):
    """Where `user` stands on the leaderboard: 1 + everyone ranked strictly ahead of them, so
    players tied on kills, level and points share a rank."""
    ahead = db.or_(
        User.kills > user.kills,
        db.and_(User.kills == user.kills, User.level > user.level),
        db.and_(User.kills == user.kills, User.level == user.level, User.points > user.points),
    )
    return 1 + db.session.scalar(db.select(db.func.count(User.id)).where(ahead))


def public_player(user):
    """What anyone can see about a player. No money, no gear."""
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "level": user.level,
        "prestige": user.prestige,
        "kills": user.kills,
        "points": user.points,
        "fights_won": user.fights_won,
        "alive": not rules.is_dead(user),
        "bot": user.is_bot,
    }


def player_state(user, holdings, now):
    """Everything the game screen shows about the logged-in player."""
    attack, defense = rules.power(user, holdings)
    events = db.session.scalars(
        db.select(Event)
        .where(Event.user_id == user.id)
        .order_by(Event.id.desc())
        .limit(EVENTS_SHOWN)
    ).all()
    return {
        "player": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "level": user.level,
            "prestige": user.prestige,
            "points": user.points,
            "points_needed": rules.points_to_next_level(user.level),
            "money": user.money,
            "bank": user.bank,
            "skill_points": user.skill_points,
            "base_attack": user.attack,
            "base_defense": user.defense,
            "attack": attack,
            "defense": defense,
            "kills": user.kills,
            "jobs_done": user.jobs_done,
            "fights_won": user.fights_won,
            "fights_lost": user.fights_lost,
        },
        "bars": {
            bar: {
                "value": getattr(user, bar),
                "max": rules.bar_max(user, bar),
                "next_in": rules.seconds_to_next(user, bar, now),
                "full_in": rules.seconds_to_full(user, bar, now),
                "every": rules.REGEN_SECONDS[bar],
            }
            for bar in rules.REGEN_SECONDS
        },
        "hospital_cost": rules.hospital_cost(user),
        "bank_fee_percent": rules.BANK_FEE_PERCENT,
        "skills": rules.SKILLS,
        "loadout": {slot: g.key for slot, g in rules.loadout(holdings).items()},
        "jobs": [
            {
                "key": j.key,
                "name": j.name,
                "blurb": j.blurb,
                "min_level": j.min_level,
                "energy": j.energy,
                "payout": j.payout,
                "points": j.points,
                "robbery": j.robbery,
            }
            for j in JOBS
        ],
        "gear": [
            {
                "key": g.key,
                "name": g.name,
                "slot": g.slot,
                "attack": g.attack,
                "defense": g.defense,
                "price": g.price,
                "min_level": g.min_level,
                "owned": bool(holdings.get(g.key)),
            }
            for g in GEAR
        ],
        "rackets": [
            {
                "key": r.key,
                "name": r.name,
                "blurb": r.blurb,
                "income": r.income,
                "min_level": r.min_level,
                "owned": holdings.get(r.key, 0),
                "price": rules.racket_price(r, holdings.get(r.key, 0)),
            }
            for r in RACKETS
        ],
        "income": {
            "per_hour": rules.income_per_hour(holdings),
            "uncollected": rules.uncollected_income(user, holdings, now),
            "cap_hours": rules.INCOME_CAP_HOURS,
        },
        "events": [
            {"text": e.text, "at": e.created_at.isoformat() + "Z", "id": e.id} for e in events
        ],
    }


# --- Actions -----------------------------------------------------------------------------------


@bp.post("/api/do/<name>")
@login_required
@limiter.limit(ACTION_LIMIT)
def do(name):
    if name not in ACTIONS:
        return jsonify({"error": "Unknown action."}), 404
    data = request.get_json(silent=True) or {}
    player = locked_player()
    now = utcnow()
    outcome, holdings = perform(player, name, data, now, random)
    db.session.commit()
    return jsonify(
        {
            "message": outcome.message,
            "ok": outcome.ok,
            "state": player_state(player, holdings, now),
        }
    )


def perform(player, name, data, now, rng):
    """Run one action for `player` and stage the changes (the caller commits). Bots use this
    too, so they play by exactly the same rules as people. Returns (Outcome, holdings)."""
    rules.regenerate(player, now)
    holdings = load_holdings(player)
    before = dict(holdings)
    outcome = ACTIONS[name](player, holdings, data, now, rng)
    save_holdings(player, before, holdings)
    return outcome, holdings


def act_job(player, holdings, data, now, rng):
    job = JOBS_BY_KEY.get(data.get("job"))
    if job is None:
        return rules.fail("No such job.")
    target = random_other_player(player) if job.robbery else None
    if target is not None:
        rules.regenerate(target, now)
    outcome = rules.run_job(player, job, target, rng)
    if outcome.event and target is not None:
        add_event(target, outcome.event)
    return outcome


def act_attack(player, holdings, data, now, rng):
    defender_id = data.get("defender_id")
    defender = (
        db.session.get(User, defender_id, populate_existing=True, with_for_update=True)
        if isinstance(defender_id, int) and not isinstance(defender_id, bool)
        else None
    )
    if defender is None:
        return rules.fail("Player not found.")
    rules.regenerate(defender, now)
    defender_holdings = load_holdings(defender) if defender.id != player.id else holdings
    outcome = rules.attack(player, defender, holdings, defender_holdings, rng)
    if outcome.event:
        add_event(defender, outcome.event)
    return outcome


def act_hospital(player, holdings, data, now, rng):
    return rules.hospital(player)


def act_buy(player, holdings, data, now, rng):
    item = data.get("item")
    if item in GEAR_BY_KEY:
        return rules.buy_gear(player, GEAR_BY_KEY[item], holdings)
    if item in RACKETS_BY_KEY:
        return rules.buy_racket(player, RACKETS_BY_KEY[item], holdings, now)
    return rules.fail("The shop doesn't carry that.")


def act_collect(player, holdings, data, now, rng):
    return rules.collect_income(player, holdings, now)


def act_bank(player, holdings, data, now, rng):
    amount = data.get("amount")
    if not isinstance(amount, int) or isinstance(amount, bool):
        return rules.fail("Enter a whole number of dollars.")
    if data.get("direction") == "deposit":
        return rules.deposit(player, amount)
    if data.get("direction") == "withdraw":
        return rules.withdraw(player, amount)
    return rules.fail("Deposit or withdraw?")


def act_skill(player, holdings, data, now, rng):
    return rules.spend_skill_point(player, data.get("skill"))


ACTIONS = {
    "job": act_job,
    "attack": act_attack,
    "hospital": act_hospital,
    "buy": act_buy,
    "collect": act_collect,
    "bank": act_bank,
    "skill": act_skill,
}


# --- Helpers -----------------------------------------------------------------------------------


def lock_for_write():
    """Make this request the only one writing until it commits.

    Without this, two requests that land at the same moment (two quick clicks, or a player and
    a bot) both read the same starting numbers and the second save wipes out the first. That
    turns into free money: buy two things, pay for one. SQLite only allows one writer anyway,
    so "BEGIN IMMEDIATE" just claims that slot up front instead of at the first UPDATE.
    Other databases lock each row as it's read instead (with_for_update below).
    """
    connection = db.session.connection()
    if connection.dialect.name != "sqlite":
        return
    raw = connection.connection.dbapi_connection
    if not raw.in_transaction:
        raw.execute("BEGIN IMMEDIATE")


def locked_player():
    """The logged-in player, re-read after taking the write lock so the numbers are current."""
    lock_for_write()
    return db.session.get(User, current_user.id, populate_existing=True, with_for_update=True)


def load_holdings(user):
    rows = db.session.scalars(db.select(Holding).where(Holding.user_id == user.id)).all()
    return {row.item: row.quantity for row in rows}


def save_holdings(user, before, after):
    for item, quantity in after.items():
        if before.get(item) == quantity:
            continue
        row = db.session.scalar(db.select(Holding).filter_by(user_id=user.id, item=item))
        if row is None:
            db.session.add(Holding(user_id=user.id, item=item, quantity=quantity))
        else:
            row.quantity = quantity


def add_event(user, text):
    db.session.add(Event(user_id=user.id, text=text))
    db.session.flush()
    keep = (
        db.select(Event.id)
        .where(Event.user_id == user.id)
        .order_by(Event.id.desc())
        .limit(EVENTS_KEPT)
    )
    db.session.execute(db.delete(Event).where(Event.user_id == user.id, Event.id.not_in(keep)))


def find_targets(me, limit=TARGETS_SHOWN):
    """A handful of living players around `me`'s level, in random order. Tops up with anyone
    alive when there aren't enough players nearby."""
    alive_others = db.select(User).where(User.id != me.id, User.health > 0)
    found = db.session.scalars(
        alive_others.where(User.level.between(me.level - 5, me.level + 10))
        .order_by(db.func.random())
        .limit(limit)
    ).all()
    if len(found) < limit:
        seen = [u.id for u in found]
        found += db.session.scalars(
            alive_others.where(User.id.not_in(seen))
            .order_by(db.func.random())
            .limit(limit - len(found))
        ).all()
    return found


def random_other_player(user):
    """Pick one random player who isn't `user`, without loading everyone into memory."""
    count = db.session.scalar(db.select(db.func.count(User.id)).where(User.id != user.id))
    if not count:
        return None
    return db.session.scalars(
        db.select(User)
        .where(User.id != user.id)
        .order_by(User.id)
        .offset(random.randrange(count))  # noqa: S311 - game dice, not security
        .limit(1)
    ).first()
