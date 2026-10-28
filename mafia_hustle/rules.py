"""Game rules. Plain functions with no Flask in them, so they're easy to test.

Every function that rolls dice takes an `rng` argument (anything with randint/random/choice,
like the `random` module). Tests pass in a seeded `random.Random` to get repeatable results.
"""

MAX_LEVEL = 60
BASE_HEALTH = 100
HEALTH_PER_LEVEL = 10
POINTS_PER_ACTION = 10


def max_health(level):
    return BASE_HEALTH + (level - 1) * HEALTH_PER_LEVEL


def points_to_next_level(level):
    # Same curve as before (level * 100 * (1 + level / 10)), rewritten to stay an integer.
    return 100 * level + 10 * level * level


def points_to_next_prestige(prestige):
    return points_to_next_level(MAX_LEVEL) * 2**prestige


def gain_points(user, amount):
    """Add points and apply every level-up (or prestige) they pay for."""
    user.points += amount
    while True:
        if user.level < MAX_LEVEL:
            needed = points_to_next_level(user.level)
            if user.points < needed:
                return
            user.points -= needed
            user.level += 1
            user.health = max_health(user.level)
        else:
            needed = points_to_next_prestige(user.prestige)
            if user.points < needed:
                return
            user.points -= needed
            user.prestige += 1


def take_damage(user, amount):
    user.health = max(0, user.health - amount)


def is_dead(user):
    return user.health <= 0


def attack(attacker, defender, rng):
    """Resolve an attack. Returns a message for the attacker."""
    if attacker.id == defender.id:
        return "You can't attack yourself."
    if is_dead(attacker):
        return "You're dead. Heal up before you pick a fight."
    if is_dead(defender):
        return f"{defender.username} is already dead."

    recoil = rng.randint(5, 15)
    take_damage(attacker, recoil)
    take_damage(defender, 10)

    message = f"You attacked {defender.username} and took {recoil} damage."
    if is_dead(defender):
        attacker.kills += 1
        message += f" {defender.username} is down. That's a kill."

    gain_points(attacker, POINTS_PER_ACTION)
    return message + f" +{POINTS_PER_ACTION} points."


def run_job(user, targets, rng):
    """Run a job: rob a random player. Returns a message for the player."""
    if is_dead(user):
        return "You're dead. Heal up before you take a job."

    damage = rng.randint(5, 15)
    take_damage(user, damage)
    if is_dead(user):
        return f"The job went sideways. You took {damage} damage and died."

    if not targets:
        return f"Nobody to rob yet. You took {damage} damage for nothing."

    target = rng.choice(targets)
    # Never take more than the target has, so nobody's money goes negative.
    stolen = min(rng.randint(10, 100), max(target.money, 0))
    user.money += stolen
    target.money -= stolen

    gain_points(user, POINTS_PER_ACTION)
    return (
        f"You stole ${stolen} from {target.username} and took {damage} damage. "
        f"+{POINTS_PER_ACTION} points."
    )


def heal_up(user, rng):
    """Search for food. Coin flip to find some."""
    if not rng.choice([True, False]):
        return "You didn't find any food."
    amount = rng.randint(10, 30)
    user.health = min(user.health + amount, max_health(user.level))
    return f"You found food and healed {amount} health."
