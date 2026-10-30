import random
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from mafia_hustle import rules
from mafia_hustle.catalog import GEAR_BY_KEY, JOBS_BY_KEY, RACKETS, RACKETS_BY_KEY

NOW = datetime(2026, 10, 30, 12, 0, 0)


def player(id=1, username="vito", **stats):
    defaults = dict(
        health=100,
        money=1000,
        bank=0,
        level=1,
        points=0,
        kills=0,
        prestige=0,
        energy=20,
        stamina=10,
        max_energy=20,
        max_stamina=10,
        attack=5,
        defense=5,
        health_bonus=0,
        skill_points=0,
        jobs_done=0,
        fights_won=0,
        fights_lost=0,
        energy_at=None,
        stamina_at=None,
        health_at=None,
        income_at=None,
    )
    defaults.update(stats)
    return SimpleNamespace(id=id, username=username, **defaults)


# --- Levels and bars ---------------------------------------------------------------------------


def test_points_curve_matches_original_formula():
    for level in range(1, 61):
        assert rules.points_to_next_level(level) == pytest.approx(level * 100 * (1 + level / 10))


def test_level_up_refills_bars_and_hands_out_skill_points():
    p = player(health=20, energy=0, stamina=0)
    assert rules.gain_points(p, 110) == 1
    assert (p.level, p.points, p.skill_points) == (2, 0, 3)
    assert p.health == rules.max_health(p) == 110
    assert (p.energy, p.stamina) == (20, 10)


def test_gain_points_applies_multiple_level_ups_at_once():
    p = player()
    assert rules.gain_points(p, 110 + 240 + 5) == 2
    assert (p.level, p.points, p.skill_points) == (3, 5, 6)


def test_max_level_rolls_into_prestige():
    p = player(level=60)
    rules.gain_points(p, rules.points_to_next_prestige(0))
    assert p.level == 60
    assert p.prestige == 1
    assert rules.points_to_next_prestige(1) == 2 * rules.points_to_next_prestige(0)


def test_regeneration_counts_whole_ticks_and_keeps_the_remainder():
    tick = rules.REGEN_SECONDS["energy"]
    p = player(energy=5, energy_at=NOW)
    later = NOW + timedelta(seconds=2.5 * tick)
    rules.regenerate(p, later)
    assert p.energy == 7
    assert p.energy_at == NOW + timedelta(seconds=2 * tick)
    assert rules.seconds_to_next(p, "energy", later) == tick // 2


def test_energy_and_stamina_take_most_of_a_day_to_refill():
    p = player(energy=0, stamina=0, energy_at=NOW, stamina_at=NOW)
    for bar in ("energy", "stamina"):
        hours = rules.seconds_to_full(p, bar, NOW) / 3600
        assert 8 <= hours <= 16, (bar, hours)
    rules.regenerate(p, NOW + timedelta(hours=1))
    assert p.energy <= 3 and p.stamina <= 1


def test_seconds_to_full():
    tick = rules.REGEN_SECONDS["stamina"]
    p = player(stamina=7, stamina_at=NOW)
    assert rules.seconds_to_full(p, "stamina", NOW + timedelta(seconds=10)) == 3 * tick - 10
    assert rules.seconds_to_full(player(), "stamina", NOW) is None


def test_regeneration_stops_at_the_cap():
    p = player(energy=18, stamina=0, health=1, energy_at=NOW, stamina_at=NOW, health_at=NOW)
    rules.regenerate(p, NOW + timedelta(days=1))
    assert (p.energy, p.stamina, p.health) == (20, 10, 100)
    assert rules.seconds_to_next(p, "energy", NOW) is None


def test_full_bars_dont_bank_time():
    p = player(energy=20, energy_at=NOW - timedelta(hours=5))
    rules.regenerate(p, NOW)
    assert p.energy_at == NOW
    p.energy = 0
    rules.regenerate(p, NOW + timedelta(seconds=rules.REGEN_SECONDS["energy"] - 1))
    assert p.energy == 0


def test_first_regeneration_just_starts_the_clock():
    p = player(energy=0)
    rules.regenerate(p, NOW)
    assert p.energy == 0 and p.energy_at == NOW


# --- Fights ------------------------------------------------------------------------------------


def test_cannot_attack_yourself():
    p = player()
    outcome = rules.attack(p, p, {}, {}, random.Random(1))
    assert not outcome.ok and "yourself" in outcome.message
    assert p.stamina == 10


@pytest.mark.parametrize(
    ("attacker_stats", "defender_stats", "expected"),
    [
        ({"health": 0}, {}, "dead"),
        ({"health": 10}, {}, "at least"),
        ({"stamina": 0}, {}, "stamina"),
        ({}, {"health": 0}, "already down"),
    ],
)
def test_fights_that_cant_happen(attacker_stats, defender_stats, expected):
    attacker = player(id=1, **attacker_stats)
    defender = player(id=2, username="sonny", **defender_stats)
    outcome = rules.attack(attacker, defender, {}, {}, random.Random(1))
    assert not outcome.ok and expected in outcome.message


def test_much_stronger_attacker_always_wins_and_takes_cash():
    for seed in range(30):
        attacker, defender = player(id=1, attack=50), player(id=2, username="sonny", defense=1)
        outcome = rules.attack(attacker, defender, {}, {}, random.Random(seed))
        assert outcome.ok
        assert attacker.fights_won == 1 and defender.fights_lost == 1
        assert attacker.money + defender.money == 2000
        assert defender.money < 1000
        assert attacker.stamina == 9
        assert "jumped you" in outcome.event


def test_much_stronger_defender_always_wins():
    for seed in range(30):
        attacker, defender = player(id=1), player(id=2, username="sonny", defense=50)
        outcome = rules.attack(attacker, defender, {}, {}, random.Random(seed))
        assert not outcome.ok
        assert defender.fights_won == 1
        assert attacker.money == defender.money == 1000
        assert attacker.health < defender.health


def test_gear_counts_in_fights():
    attacker, defender = player(id=1, attack=1), player(id=2, username="sonny", defense=10)
    rifle = {"rifle": 1}
    assert rules.power(attacker, rifle) == (21, 8)
    assert rules.attack(attacker, defender, rifle, {}, random.Random(4)).ok


def test_knockout_counts_as_a_kill():
    attacker, defender = player(id=1, attack=50), player(id=2, username="sonny", health=5)
    outcome = rules.attack(attacker, defender, {}, {}, random.Random(1))
    assert defender.health == 0
    assert attacker.kills == 1
    assert "kill" in outcome.message


def test_loot_never_drives_money_negative():
    attacker, defender = player(id=1, attack=50), player(id=2, username="sonny", money=0)
    rules.attack(attacker, defender, {}, {}, random.Random(1))
    assert defender.money == 0


def test_loadout_uses_the_best_piece_in_each_slot():
    holdings = {"knuckles": 1, "sawedoff": 1, "overcoat": 1, "smg": 0, "shoeshine": 4}
    best = rules.loadout(holdings)
    assert best["weapon"].key == "sawedoff"
    assert best["armor"].key == "overcoat"
    assert "ride" not in best


# --- Jobs --------------------------------------------------------------------------------------


def test_job_pays_and_costs_energy():
    p = player()
    job = JOBS_BY_KEY["boost"]
    outcome = rules.run_job(p, job, None, random.Random(1))
    assert outcome.ok
    assert p.energy == 17
    assert job.payout[0] <= p.money - 1000 <= job.payout[1]
    assert p.points == job.points and p.jobs_done == 1


def test_locked_and_unaffordable_jobs():
    p = player(energy=2)
    assert "level 6" in rules.run_job(p, JOBS_BY_KEY["truck"], None, random.Random(1)).message
    assert "3 energy" in rules.run_job(p, JOBS_BY_KEY["boost"], None, random.Random(1)).message
    assert p.energy == 2 and p.money == 1000


def test_robbery_never_drives_money_negative():
    robber, broke = player(id=1, level=2, energy=100), player(id=2, username="fredo", money=5)
    rng = random.Random(3)
    for _ in range(5):
        robber.health = 100
        rules.run_job(robber, JOBS_BY_KEY["crowd"], broke, rng)
    assert broke.money >= 0
    assert robber.money + broke.money == 1005


def test_robbery_tells_the_victim_without_naming_the_thief():
    robber, mark = player(id=1, level=2), player(id=2, username="fredo")
    outcome = rules.run_job(robber, JOBS_BY_KEY["crowd"], mark, random.Random(7))
    assert outcome.message.count("$") == 1
    assert "vito" not in outcome.event


def test_robbery_with_nobody_to_rob_costs_nothing():
    p = player(level=2)
    outcome = rules.run_job(p, JOBS_BY_KEY["crowd"], None, random.Random(1))
    assert "Nobody" in outcome.message
    assert p.energy == 20 and p.money == 1000


# --- Spending ----------------------------------------------------------------------------------


def test_hospital_heals_for_a_price():
    p = player(health=40)
    assert rules.hospital_cost(p) == 60 * 3
    assert rules.hospital(p).ok
    assert p.health == 100 and p.money == 1000 - 180
    assert not rules.hospital(p).ok


def test_hospital_wants_cash_up_front():
    p = player(health=0, money=10)
    assert not rules.hospital(p).ok
    assert p.health == 0 and p.money == 10


def test_buying_gear():
    p, holdings = player(money=500), {}
    knuckles, revolver = GEAR_BY_KEY["knuckles"], GEAR_BY_KEY["snubnose"]
    assert rules.buy_gear(p, knuckles, holdings).ok
    assert holdings == {"knuckles": 1} and p.money == 100
    assert "already" in rules.buy_gear(p, knuckles, holdings).message
    assert "level 2" in rules.buy_gear(p, revolver, holdings).message
    p.level = 2
    assert "$1,500" in rules.buy_gear(p, revolver, holdings).message


def test_racket_prices_climb():
    stand = RACKETS_BY_KEY["shoeshine"]
    prices = [rules.racket_price(stand, n) for n in range(4)]
    assert prices == [2000, 2500, 3120, 3910]
    assert all(isinstance(price, int) for price in prices)


def test_each_racket_tier_costs_exponentially_more():
    prices = [r.price for r in RACKETS]
    assert prices[0] == 2000
    assert all(later == 5 * earlier for earlier, later in zip(prices, prices[1:], strict=False))
    assert prices[-1] >= 6_000_000
    # Later rackets also take longer to pay for themselves.
    payback = [r.price / r.income for r in RACKETS]
    assert payback == sorted(payback)


def test_racket_income_accrues_and_caps():
    p = player(money=0, income_at=NOW)
    holdings = {"shoeshine": 2}
    assert rules.uncollected_income(p, holdings, NOW + timedelta(minutes=30)) == 40
    capped = rules.uncollected_income(p, holdings, NOW + timedelta(days=3))
    assert capped == 80 * rules.INCOME_CAP_HOURS
    assert rules.collect_income(p, holdings, NOW + timedelta(hours=1)).ok
    assert p.money == 80 and p.income_at == NOW + timedelta(hours=1)
    assert not rules.collect_income(p, holdings, NOW + timedelta(hours=1)).ok


def test_buying_a_racket_collects_first():
    p = player(money=5000, income_at=NOW)
    holdings = {"shoeshine": 1}
    later = NOW + timedelta(hours=2)
    assert rules.buy_racket(p, RACKETS_BY_KEY["shoeshine"], holdings, later).ok
    assert holdings == {"shoeshine": 2}
    assert p.money == 5000 + 80 - 2500
    assert p.income_at == later


def test_bank_keeps_a_cut_of_deposits():
    p = player(money=1000)
    assert rules.deposit(p, 101).ok
    assert p.money == 899 and p.bank == 101 - 11
    assert not rules.deposit(p, 5000).ok
    assert not rules.deposit(p, 0).ok
    assert rules.withdraw(p, 90).ok
    assert p.bank == 0 and p.money == 989
    assert not rules.withdraw(p, 1).ok


@pytest.mark.parametrize(
    ("skill", "field", "change"),
    [
        ("attack", "attack", 1),
        ("defense", "defense", 1),
        ("energy", "max_energy", 2),
        ("stamina", "max_stamina", 1),
        ("health", "health_bonus", 10),
    ],
)
def test_skill_points(skill, field, change):
    p = player(skill_points=1)
    before = getattr(p, field)
    assert rules.spend_skill_point(p, skill).ok
    assert getattr(p, field) == before + change
    assert not rules.spend_skill_point(p, skill).ok
    assert not rules.spend_skill_point(player(skill_points=1), "luck").ok


def test_health_skill_doesnt_revive_the_dead():
    p = player(health=0, skill_points=1)
    rules.spend_skill_point(p, "health")
    assert p.health == 0
