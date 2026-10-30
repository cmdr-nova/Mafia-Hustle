"""Everything you can do or buy in the game. Plain data, so balancing is a matter of editing
numbers here. Keys are stored in the database (Holding.item), so never rename one."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Job:
    key: str
    name: str
    blurb: str
    min_level: int
    energy: int
    payout: tuple[int, int]  # dollars, low and high
    points: int
    damage: tuple[int, int]  # health lost, low and high
    # Steal from another player instead of a fixed payout.
    robbery: bool = False


@dataclass(frozen=True)
class Gear:
    key: str
    name: str
    slot: str  # "weapon", "armor" or "ride"
    attack: int
    defense: int
    price: int
    min_level: int


@dataclass(frozen=True)
class Racket:
    key: str
    name: str
    blurb: str
    price: int  # for the first one; each extra costs more
    income: int  # dollars per hour, per racket
    min_level: int


# fmt: off
JOBS = [
    #   key        name                              blurb                                 lvl  nrg  payout          pts  damage
    Job("numbers", "Run numbers",                    "Collect slips on the corner.",         1,   1, (40, 90),          4, (0, 2)),
    Job("boost",   "Boost a parked car",             "Nobody locks a Packard.",              1,   3, (130, 260),       12, (0, 5)),
    Job("crowd",   "Work the crowd",                 "Lift a wallet from another player.",   2,   2, (0, 0),            8, (0, 6), robbery=True),
    Job("pawn",    "Lean on a pawnbroker",           "He'll see reason.",                    3,   5, (300, 550),       20, (2, 9)),
    Job("truck",   "Hijack a cigarette truck",       "Route 9, after midnight.",             6,   8, (800, 1400),      30, (4, 14)),
    Job("cards",   "Rig a back-room card game",      "Marked deck, quiet dealer.",          10,  10, (1700, 2800),    40, (3, 12)),
    Job("docks",   "Clean out a dockside warehouse", "Bring a big truck.",                  15,  14, (3400, 5200),    60, (8, 20)),
    Job("armored", "Knock over an armored car",      "Loud, fast, rich.",                   25,  20, (7500, 12500),   90, (10, 28)),
    Job("count",   "Skim the casino count room",     "The house always loses.",             40,  28, (19000, 31000), 135, (10, 32)),
]
# fmt: on

GEAR = [
    Gear("knuckles", "Brass knuckles", "weapon", 2, 0, 400, 1),
    Gear("snubnose", "Snub-nose revolver", "weapon", 5, 1, 1500, 2),
    Gear("sawedoff", "Sawed-off shotgun", "weapon", 9, 1, 4500, 5),
    Gear("smg", "Drum-fed submachine gun", "weapon", 14, 2, 12000, 10),
    Gear("rifle", "Scoped hunting rifle", "weapon", 20, 3, 30000, 20),
    Gear("overcoat", "Heavy wool overcoat", "armor", 0, 2, 300, 1),
    Gear("leather", "Leather jacket", "armor", 0, 4, 1200, 2),
    Gear("steelvest", "Steel-lined vest", "armor", 1, 8, 5000, 6),
    Gear("kevlar", "Kevlar vest", "armor", 1, 13, 14000, 12),
    Gear("platesuit", "Plated three-piece suit", "armor", 2, 19, 35000, 22),
    Gear("sedan", "Rusty sedan", "ride", 1, 1, 800, 1),
    Gear("coupe", "Getaway coupe", "ride", 3, 3, 4000, 4),
    Gear("limo", "Armored limousine", "ride", 4, 8, 15000, 12),
    Gear("speedboat", "Rum-runner speedboat", "ride", 7, 5, 40000, 25),
]

# fmt: off
# Racket prices grow exponentially down the list: each tier costs RACKET_TIER_GROWTH times the
# one before ($2k, $10k, $50k, $250k, $1.25M, $6.25M, ...). Income grows slower than price, so
# later rackets take longer to pay for themselves. A racket added to the end of the list is
# priced automatically, and it costs more than everything above it.
RACKET_BASE_PRICE = 2000
RACKET_TIER_GROWTH = 5
# Each extra copy of the same racket costs this much more than the last one.
RACKET_COPY_GROWTH = 1.25

_RACKETS = [
    # key           name               blurb                          $/hour  level
    ("shoeshine",  "Shoeshine stand", "Shines shoes, passes notes.",     40,  1),
    ("laundromat", "Laundromat",      "Washes more than shirts.",       150,  3),
    ("bar",        "Corner bar",      "Last call is a suggestion.",     450,  8),
    ("pawnshop",   "Pawn shop",       "No questions asked.",           1200, 15),
    ("nightclub",  "Nightclub",       "Live jazz, back door.",         3600, 25),
    ("casino",     "Casino floor",    "Odds in our favor.",           12000, 40),
]
# fmt: on
RACKETS = [
    Racket(key, name, blurb, RACKET_BASE_PRICE * RACKET_TIER_GROWTH**tier, income, level)
    for tier, (key, name, blurb, income, level) in enumerate(_RACKETS)
]

JOBS_BY_KEY = {j.key: j for j in JOBS}
GEAR_BY_KEY = {g.key: g for g in GEAR}
RACKETS_BY_KEY = {r.key: r for r in RACKETS}
SLOTS = ("weapon", "armor", "ride")
