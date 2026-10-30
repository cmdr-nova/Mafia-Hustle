import random

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from . import rules
from .extensions import db, limiter
from .models import User

bp = Blueprint("game", __name__)

# Plenty for a human clicking, not enough for a script hammering the server.
ACTION_LIMIT = "2 per second;60 per minute"


def player_json(user):
    return {
        "id": user.id,
        "username": user.username,
        "health": user.health,
        "max_health": rules.max_health(user.level),
        "money": user.money,
        "level": user.level,
        "points": user.points,
        "points_needed": rules.points_to_next_level(user.level),
        "kills": user.kills,
        "prestige": user.prestige,
    }


@bp.route("/")
@login_required
def index():
    return render_template("index.html")


@bp.get("/api/player-info")
@login_required
def player_info():
    return jsonify(player_json(current_user))


@bp.get("/api/leaderboard")
def leaderboard():
    top = db.session.scalars(
        db.select(User).order_by(User.kills.desc(), User.points.desc()).limit(10)
    ).all()
    return jsonify(
        {
            "leaderboard": [
                {
                    "id": u.id,
                    "username": u.username,
                    "kills": u.kills,
                    "points": u.points,
                    "level": u.level,
                    "alive": not rules.is_dead(u),
                }
                for u in top
            ]
        }
    )


@bp.post("/api/attack")
@login_required
@limiter.limit(ACTION_LIMIT)
def attack():
    defender_id = (request.get_json(silent=True) or {}).get("defender_id")
    defender = db.session.get(User, defender_id) if isinstance(defender_id, int) else None
    if defender is None:
        return jsonify({"error": "Player not found."}), 404

    message = rules.attack(current_user, defender, random)
    db.session.commit()
    return jsonify({"message": message})


@bp.post("/api/run-job")
@login_required
@limiter.limit(ACTION_LIMIT)
def run_job():
    message = rules.run_job(current_user, random_other_player(current_user), random)
    db.session.commit()
    return jsonify({"message": message})


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


@bp.post("/api/heal-up")
@login_required
@limiter.limit(ACTION_LIMIT)
def heal_up():
    message = rules.heal_up(current_user, random)
    db.session.commit()
    return jsonify({"message": message})
