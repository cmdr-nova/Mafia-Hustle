import random
from types import SimpleNamespace

import pytest

from mafia_hustle import rules


def player(id=1, username="vito", **stats):
    defaults = dict(health=100, money=1000, level=1, points=0, kills=0, prestige=0)
    defaults.update(stats)
    return SimpleNamespace(id=id, username=username, **defaults)


def test_points_curve_matches_original_formula():
    for level in range(1, 61):
        assert rules.points_to_next_level(level) == pytest.approx(level * 100 * (1 + level / 10))


def test_gain_points_levels_up_and_refills_health():
    p = player(health=20)
    rules.gain_points(p, 110)
    assert p.level == 2
    assert p.points == 0
    assert p.health == rules.max_health(2) == 110


def test_gain_points_applies_multiple_level_ups_at_once():
    p = player()
    rules.gain_points(p, 110 + 240 + 5)
    assert p.level == 3
    assert p.points == 5


def test_max_level_rolls_into_prestige():
    p = player(level=60)
    rules.gain_points(p, rules.points_to_next_prestige(0))
    assert p.level == 60
    assert p.prestige == 1
    assert rules.points_to_next_prestige(1) == 2 * rules.points_to_next_prestige(0)


def test_cannot_attack_yourself():
    p = player()
    assert "yourself" in rules.attack(p, p, random.Random(1))
    assert p.health == 100 and p.points == 0


def test_dead_players_cannot_attack_or_be_attacked():
    alive, dead = player(id=1), player(id=2, username="sonny", health=0)
    assert "dead" in rules.attack(dead, alive, random.Random(1))
    assert "dead" in rules.attack(alive, dead, random.Random(1))
    assert alive.health == 100


def test_attack_damages_both_and_counts_kills():
    attacker, defender = player(id=1), player(id=2, username="sonny", health=10)
    message = rules.attack(attacker, defender, random.Random(1))
    assert defender.health == 0
    assert attacker.kills == 1
    assert 85 <= attacker.health <= 95
    assert attacker.points == 10
    assert "$" not in message


def test_run_job_never_drives_money_negative():
    robber, broke = player(id=1), player(id=2, username="fredo", money=5)
    rng = random.Random(3)
    for _ in range(5):
        robber.health = 100
        rules.run_job(robber, [broke], rng)
    assert broke.money == 0
    assert robber.money == 1005


def test_run_job_message_has_no_stray_dollar_signs():
    robber, mark = player(id=1), player(id=2, username="fredo")
    message = rules.run_job(robber, [mark], random.Random(7))
    assert message.count("$") == 1  # just the amount
    assert "$fredo" not in message


def test_run_job_with_nobody_to_rob():
    p = player()
    assert "Nobody to rob" in rules.run_job(p, [], random.Random(1))
    assert p.money == 1000


@pytest.mark.parametrize("seed", range(20))
def test_heal_never_exceeds_max_health(seed):
    p = player(health=95)
    rules.heal_up(p, random.Random(seed))
    assert 95 <= p.health <= rules.max_health(1)
