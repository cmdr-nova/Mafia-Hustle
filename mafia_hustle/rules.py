"""Game rules. Plain functions with no Flask in them, so they're easy to test.

Every function that rolls dice takes an `rng` argument (anything with randint/uniform/choice,
like the `random` module). Tests pass in a seeded `random.Random` to get repeatable results.

Functions that touch what a player owns take `holdings`, a plain dict of {item key: quantity},
and change it in place. game.py loads it from the database and saves it back.
"""

from dataclasses import dataclass
from datetime import timedelta

from .catalog import GEAR_BY_KEY, RACKET_COPY_GROWTH, RACKETS_BY_KEY, SLOTS

MAX_LEVEL = 60
BASE_HEALTH = 100
HEALTH_PER_LEVEL = 10
SKILL_POINTS_PER_LEVEL = 3
# Seconds for each bar to gain one point. Energy and stamina are slow on purpose: a full refill
# of the starting bars takes most of a day (20 energy in 10 hours, 10 stamina in 10 hours), so
# you play a session, then come back tomorrow. Health stays quick so a beating isn't a lockout.
REGEN_SECONDS = {"energy": 30 * 60, "stamina": 60 * 60, "health": 20}
# Racket income piles up for at most this long before someone has to come collect it.
INCOME_CAP_HOURS = 12
BANK_FEE_PERCENT = 10
# Too beat up to start a fight below this.
MIN_FIGHT_HEALTH = 20
SKILLS = {
    "attack": "+1 attack",
    "defense": "+1 defense",
    "energy": "+2 max energy",
    "stamina": "+1 max stamina",
    "health": "+10 max health",
}


@dataclass
class Outcome:
    message: str
    ok: bool = True
    # Something to tell the other player involved (shows up on their wire), if any.
    event: str | None = None


def fail(message):
    return Outcome(message, ok=False)


def money(amount):
    return f"${amount:,}"


# --- Levels and bars ---------------------------------------------------------------------------


def max_health(user):
    return BASE_HEALTH + (user.level - 1) * HEALTH_PER_LEVEL + user.health_bonus


def bar_max(user, bar):
    return {"energy": user.max_energy, "stamina": user.max_stamina, "health": max_health(user)}[bar]


def points_to_next_level(level):
    # Same curve as before (level * 100 * (1 + level / 10)), rewritten to stay an integer.
    return 100 * level + 10 * level * level


def points_to_next_prestige(prestige):
    return points_to_next_level(MAX_LEVEL) * 2**prestige


def refill(user):
    user.health = max_health(user)
    user.energy = max(user.energy, user.max_energy)
    user.stamina = max(user.stamina, user.max_stamina)


def gain_points(user, amount):
    """Add points and apply every level-up (or prestige) they pay for. Each level-up hands out
    skill points and refills health, energy and stamina. Returns how many levels were gained."""
    user.points += amount
    gained = 0
    while True:
        if user.level < MAX_LEVEL:
            needed = points_to_next_level(user.level)
            if user.points < needed:
                break
            user.points -= needed
            user.level += 1
            user.skill_points += SKILL_POINTS_PER_LEVEL
            gained += 1
            refill(user)
        else:
            needed = points_to_next_prestige(user.prestige)
            if user.points < needed:
                break
            user.points -= needed
            user.prestige += 1
    return gained


def with_level_up(message, user, levels):
    if levels:
        return message + f" Level up! You're now level {user.level}."
    return message


def regenerate(user, now):
    """Top up energy, stamina and health for the time that has passed. Cheap and idempotent, so
    it runs before anything reads or changes a player."""
    for bar in REGEN_SECONDS:
        at_field = f"{bar}_at"
        current, cap, at = getattr(user, bar), bar_max(user, bar), getattr(user, at_field)
        if current >= cap or at is None:
            setattr(user, at_field, now)
            continue
        seconds = REGEN_SECONDS[bar]
        ticks = int((now - at).total_seconds() // seconds)
        if ticks <= 0:
            continue
        setattr(user, bar, min(cap, current + ticks))
        if getattr(user, bar) >= cap:
            setattr(user, at_field, now)
        else:
            setattr(user, at_field, at + timedelta(seconds=ticks * seconds))


def seconds_to_next(user, bar, now):
    """Seconds until `bar` gains a point, or None when it's full."""
    at = getattr(user, f"{bar}_at")
    if getattr(user, bar) >= bar_max(user, bar) or at is None:
        return None
    return max(0, REGEN_SECONDS[bar] - int((now - at).total_seconds()))


def seconds_to_full(user, bar, now):
    """Seconds until `bar` is completely full, or None when it already is."""
    next_in = seconds_to_next(user, bar, now)
    if next_in is None:
        return None
    missing = bar_max(user, bar) - getattr(user, bar)
    return next_in + (missing - 1) * REGEN_SECONDS[bar]


def take_damage(user, amount):
    user.health = max(0, user.health - amount)


def is_dead(user):
    return user.health <= 0


# --- Gear and fighting -------------------------------------------------------------------------


def loadout(holdings):
    """The best piece of gear a player owns in each slot. Only those count in a fight."""
    best = {}
    for key, quantity in holdings.items():
        gear = GEAR_BY_KEY.get(key)
        if gear is None or quantity < 1:
            continue
        current = best.get(gear.slot)
        if current is None or gear.attack + gear.defense > current.attack + current.defense:
            best[gear.slot] = gear
    return {slot: best[slot] for slot in SLOTS if slot in best}


def power(user, holdings):
    """(attack, defense) including gear."""
    gear = loadout(holdings).values()
    return (
        user.attack + sum(g.attack for g in gear),
        user.defense + sum(g.defense for g in gear),
    )


def attack(attacker, defender, attacker_holdings, defender_holdings, rng):
    """One fight. Attack plus gear against defense plus gear, each with a +/-25% roll. The
    winner takes less damage, and a winning attacker walks off with some of the loser's cash."""
    if attacker.id == defender.id:
        return fail("You can't attack yourself.")
    if is_dead(attacker):
        return fail("You're dead. See the doc or wait to heal up.")
    if attacker.health < MIN_FIGHT_HEALTH:
        return fail(f"You need at least {MIN_FIGHT_HEALTH} health to start a fight.")
    if is_dead(defender):
        return fail(f"{defender.username} is already down.")
    if attacker.stamina < 1:
        return fail("You're out of stamina. Catch your breath.")

    attacker.stamina -= 1
    attack_power, _ = power(attacker, attacker_holdings)
    _, defense_power = power(defender, defender_holdings)
    won = attack_power * rng.uniform(0.75, 1.25) > defense_power * rng.uniform(0.75, 1.25)

    if won:
        hurt_attacker, hurt_defender = rng.randint(2, 8), rng.randint(10, 22)
        loot = min(defender.money * rng.randint(5, 12) // 100, 1000 * attacker.level)
        defender.money -= loot
        attacker.money += loot
        attacker.fights_won += 1
        defender.fights_lost += 1
        points = 10 + min(20, 2 * max(0, defender.level - attacker.level))
        message = (
            f"You beat {defender.username} and took {money(loot)}. "
            f"You lost {hurt_attacker} health. +{points} points."
        )
        event = f"{attacker.username} jumped you and took {money(loot)}."
    else:
        hurt_attacker, hurt_defender = rng.randint(10, 22), rng.randint(2, 8)
        attacker.fights_lost += 1
        defender.fights_won += 1
        points = 2
        message = (
            f"{defender.username} fought you off. You lost {hurt_attacker} health. "
            f"+{points} points."
        )
        event = f"{attacker.username} jumped you, and you sent them packing."

    take_damage(attacker, hurt_attacker)
    take_damage(defender, hurt_defender)
    if is_dead(defender):
        attacker.kills += 1
        message += f" {defender.username} is down. That's a kill."
        event += " You ended up in the gutter."
    if is_dead(attacker):
        message += " You didn't get back up."
    levels = gain_points(attacker, points)
    return Outcome(with_level_up(message, attacker, levels), ok=won, event=event)


# --- Jobs --------------------------------------------------------------------------------------


def run_job(user, job, target, rng):
    """Do a job. `target` is a random other player for robbery jobs (None if there isn't one)."""
    if user.level < job.min_level:
        return fail(f"You need level {job.min_level} for that job.")
    if is_dead(user):
        return fail("You're dead. See the doc or wait to heal up.")
    if user.energy < job.energy:
        return fail(f"That job takes {job.energy} energy. You have {user.energy}.")
    if job.robbery and target is None:
        return fail("Nobody around to rob yet.")

    user.energy -= job.energy
    damage = rng.randint(*job.damage)
    take_damage(user, damage)
    if is_dead(user):
        return fail(f"The job went sideways. You took {damage} damage and went down.")

    event = None
    if job.robbery:
        # Never take more than the target has, so nobody's money goes negative.
        take = min(target.money * rng.randint(2, 6) // 100, 250 * user.level)
        target.money -= take
        user.money += take
        message = f"You lifted {money(take)} from {target.username}."
        event = f"Someone lifted {money(take)} from your pocket."
    else:
        take = rng.randint(*job.payout)
        user.money += take
        message = f"{job.name}: you made {money(take)}."
    if damage:
        message += f" You took {damage} damage."
    message += f" +{job.points} points."

    user.jobs_done += 1
    levels = gain_points(user, job.points)
    return Outcome(with_level_up(message, user, levels), event=event)


# --- Spending money ----------------------------------------------------------------------------


def hospital_cost(user):
    return (max_health(user) - user.health) * (2 + user.level)


def hospital(user):
    cost = hospital_cost(user)
    if cost <= 0:
        return fail("You're already in one piece.")
    if user.money < cost:
        return fail(f"The doc wants {money(cost)} up front, in cash.")
    user.money -= cost
    user.health = max_health(user)
    return Outcome(f"The doc patched you up for {money(cost)}.")


def buy_gear(user, gear, holdings):
    if holdings.get(gear.key):
        return fail(f"You already own a {gear.name.lower()}.")
    if user.level < gear.min_level:
        return fail(f"You need level {gear.min_level} to buy that.")
    if user.money < gear.price:
        return fail(f"You need {money(gear.price)} in cash for that.")
    user.money -= gear.price
    holdings[gear.key] = 1
    return Outcome(f"Bought a {gear.name.lower()} for {money(gear.price)}.")


def racket_price(racket, owned):
    """Each extra racket of a kind costs RACKET_COPY_GROWTH times the last, to the nearest $10."""
    return int(round(racket.price * RACKET_COPY_GROWTH**owned, -1))


def income_per_hour(holdings):
    return sum(
        RACKETS_BY_KEY[key].income * quantity
        for key, quantity in holdings.items()
        if key in RACKETS_BY_KEY
    )


def uncollected_income(user, holdings, now):
    if user.income_at is None:
        return 0
    hours = min((now - user.income_at).total_seconds() / 3600, INCOME_CAP_HOURS)
    return int(income_per_hour(holdings) * max(0.0, hours))


def collect_income(user, holdings, now):
    amount = uncollected_income(user, holdings, now)
    user.money += amount
    user.income_at = now
    if not amount:
        return fail("Nothing to collect yet.")
    return Outcome(f"Your rackets kicked up {money(amount)}.")


def buy_racket(user, racket, holdings, now):
    if user.level < racket.min_level:
        return fail(f"You need level {racket.min_level} to buy that.")
    owned = holdings.get(racket.key, 0)
    price = racket_price(racket, owned)
    if user.money < price:
        return fail(f"You need {money(price)} in cash for that.")
    # Collect first, so the extra racket only earns from now on.
    collect_income(user, holdings, now)
    user.money -= price
    holdings[racket.key] = owned + 1
    return Outcome(f"You bought a {racket.name.lower()} for {money(price)}.")


def deposit(user, amount):
    """Money in the bank can't be stolen, but the banker keeps a cut."""
    if amount < 1 or amount > user.money:
        return fail("You don't have that much cash.")
    fee = -(-amount * BANK_FEE_PERCENT // 100)  # rounded up
    user.money -= amount
    user.bank += amount - fee
    return Outcome(f"Deposited {money(amount - fee)}. The banker kept {money(fee)}.")


def withdraw(user, amount):
    if amount < 1 or amount > user.bank:
        return fail("You don't have that much in the bank.")
    user.bank -= amount
    user.money += amount
    return Outcome(f"Withdrew {money(amount)}.")


def spend_skill_point(user, skill):
    if skill not in SKILLS:
        return fail("That's not a skill.")
    if user.skill_points < 1:
        return fail("No skill points left. Level up to earn more.")
    user.skill_points -= 1
    if skill == "attack":
        user.attack += 1
    elif skill == "defense":
        user.defense += 1
    elif skill == "energy":
        user.max_energy += 2
        user.energy += 2
    elif skill == "stamina":
        user.max_stamina += 1
        user.stamina += 1
    else:
        user.health_bonus += 10
        if not is_dead(user):
            user.health += 10
    return Outcome(f"{SKILLS[skill]}.")
