"""Computer-controlled players, so there's always someone to fight and something happening.

Bots are ordinary rows in the user table with provider "bot". They can't log in (see
load_user), and they play through game.perform(), the same code path as a person clicking,
so they follow exactly the same rules.

    flask --app mafia_hustle bots add        # create the crew (safe to run again)
    flask --app mafia_hustle bots tick       # every bot takes one turn
    flask --app mafia_hustle bots list
    flask --app mafia_hustle bots remove     # delete every bot and everything they own

On the server, deploy/mafia-hustle-bots.timer runs `bots tick` every few minutes.
"""

import random
from dataclasses import dataclass

import click
from flask import Blueprint, abort, redirect, render_template, url_for
from flask.cli import AppGroup
from flask_login import login_user

from . import rules
from .catalog import GEAR, JOBS, RACKETS, SLOTS
from .extensions import db
from .game import find_targets, load_holdings, lock_for_write, perform
from .models import Event, Holding, User, utcnow


@dataclass(frozen=True)
class Personality:
    slug: str
    name: str
    # How keen they are to pick fights (0 to 1), and which skills they favor.
    aggression: float
    skills: tuple[str, ...]


CREW = [
    Personality("knuckles", "Knuckles Malone", 0.8, ("attack", "attack", "stamina")),
    Personality("dee", "Dolores 'Dee' Vance", 0.4, ("defense", "energy", "attack")),
    Personality("tiny", "Tiny Moretti", 0.6, ("health", "defense", "attack")),
    Personality("eddie", "Eddie Two-Times", 0.7, ("attack", "stamina", "defense")),
    Personality("velma", "Velma Crane", 0.3, ("energy", "energy", "defense")),
    Personality("frank", "Silent Frank", 0.5, ("defense", "attack", "health")),
    Personality("bootsy", "Bootsy Calloway", 0.6, ("stamina", "attack", "energy")),
    Personality("nickels", "Nickels O'Hare", 0.2, ("energy", "defense", "energy")),
]
CREW_BY_SLUG = {p.slug: p for p in CREW}

cli = AppGroup("bots", help="Computer players for testing and atmosphere.")
dev_bp = Blueprint("dev", __name__, url_prefix="/dev")


def all_bots():
    return db.session.scalars(db.select(User).where(User.provider == "bot").order_by(User.id))


def personality(bot):
    return CREW_BY_SLUG.get(bot.subject.removeprefix("bot:"), CREW[0])


# --- Brain -------------------------------------------------------------------------------------


def take_turn(bot, rng, now):
    """Play one turn: spend skill points, patch up, shop, work, fight, bank. Returns a list of
    what happened, for the command line. The caller commits."""
    me = personality(bot)
    log = []

    def do(name, **data):
        outcome, holdings = perform(bot, name, data, now, rng)
        if outcome.ok or name in ("job", "attack"):
            log.append(outcome.message)
        return outcome, holdings

    while bot.skill_points > 0:
        do("skill", skill=rng.choice(me.skills))

    if bot.health < rules.max_health(bot) * 0.4 and bot.money >= rules.hospital_cost(bot):
        do("hospital")

    do("collect")
    shop(bot, do, rng)

    # Work until the energy runs out, mostly on the best job they can do.
    for _ in range(20):
        jobs = [j for j in JOBS if j.min_level <= bot.level and j.energy <= bot.energy]
        if not jobs or rules.is_dead(bot):
            break
        job = rng.choice(jobs) if rng.random() < 0.25 else max(jobs, key=lambda j: j.min_level)
        do("job", job=job.key)

    # Pick fights while there's stamina and the mood strikes.
    for _ in range(bot.stamina):
        if bot.health < rules.MIN_FIGHT_HEALTH or rng.random() > me.aggression:
            break
        targets = find_targets(bot, limit=3)
        if not targets:
            break
        do("attack", defender_id=rng.choice(targets).id)

    # Stash most of the cash where it can't be stolen.
    if bot.money > 5000 and rng.random() < 0.5:
        do("bank", direction="deposit", amount=bot.money // 2)
    return log


def shop(bot, do, rng):
    """Upgrade each gear slot when there's cash to spare, then maybe buy a racket."""
    holdings = load_holdings(bot)
    current = rules.loadout(holdings)
    for slot in SLOTS:
        have = current.get(slot)
        better = [
            g
            for g in GEAR
            if g.slot == slot
            and g.min_level <= bot.level
            and g.price <= bot.money * 0.6
            and (have is None or g.attack + g.defense > have.attack + have.defense)
        ]
        if better:
            do("buy", item=max(better, key=lambda g: g.price).key)

    holdings = load_holdings(bot)
    rackets = [r for r in RACKETS if r.min_level <= bot.level]
    if rackets and rng.random() < 0.5:
        racket = max(rackets, key=lambda r: r.min_level)
        if bot.money >= 2 * rules.racket_price(racket, holdings.get(racket.key, 0)):
            do("buy", item=racket.key)


# --- Commands ----------------------------------------------------------------------------------


@cli.command("add")
@click.option("--count", default=len(CREW), show_default=True, help="How many bots to have.")
def add_command(count):
    """Create bots (skips ones that already exist)."""
    existing = {b.subject for b in all_bots()}
    for person in CREW[:count]:
        subject = f"bot:{person.slug}"
        if subject in existing:
            continue
        db.session.add(
            User(provider="bot", subject=subject, username=person.name, display_name=person.name)
        )
        click.echo(f"Added {person.name}.")
    db.session.commit()


@cli.command("remove")
def remove_command():
    """Delete every bot, along with their gear, rackets and wire."""
    ids = [b.id for b in all_bots()]
    db.session.execute(db.delete(Holding).where(Holding.user_id.in_(ids)))
    db.session.execute(db.delete(Event).where(Event.user_id.in_(ids)))
    db.session.execute(db.delete(User).where(User.id.in_(ids)))
    db.session.commit()
    click.echo(f"Removed {len(ids)} bots.")


@cli.command("list")
def list_command():
    """Show every bot's level, money and record."""
    for bot in all_bots():
        click.echo(
            f"{bot.username:<22} lvl {bot.level:<3} hp {bot.health:<4} "
            f"cash ${bot.money:<8,} bank ${bot.bank:<8,} "
            f"won {bot.fights_won} lost {bot.fights_lost} kills {bot.kills}"
        )


@cli.command("tick")
@click.option("--quiet", is_flag=True, help="Only print errors.")
def tick_command(quiet):
    """Every bot takes one turn."""
    rng = random.Random()  # noqa: S311 - game dice, not security
    for bot_id in [b.id for b in all_bots()]:
        lock_for_write()
        bot = db.session.get(User, bot_id, populate_existing=True, with_for_update=True)
        log = take_turn(bot, rng, utcnow())
        db.session.commit()
        if not quiet:
            click.echo(f"{bot.username}: " + (" | ".join(log) or "laid low."))


# --- Local testing -----------------------------------------------------------------------------


@dev_bp.get("/login")
def dev_login_page():
    return render_template("dev_login.html", bots=list(all_bots()))


@dev_bp.post("/login/<int:user_id>")
def dev_login(user_id):
    bot = db.session.get(User, user_id)
    if bot is None or not bot.is_bot:
        abort(404)
    login_user(bot)
    return redirect(url_for("game.index"))
