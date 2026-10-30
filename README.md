# Mafia Hustle

A small browser game in the spirit of Mafia Wars. Run jobs, jump other players, buy guns, coats and cars, set up rackets that pay you by the hour, stash cash in the bank where nobody can steal it, level up to 60, then prestige forever.

Players sign in with an account they already have, on the **fediverse** (Mastodon, GoToSocial, Akkoma, and anything else that speaks the Mastodon API) or on **Bluesky** (or any AT Protocol PDS). The game never sees or stores a password. All it keeps is which account you are, your handle, and your game stats. The login tokens are revoked as soon as we know who you are.

Built with Flask, SQLAlchemy, and Flask-Login.

## Running it locally

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), which installs Python and the dependencies for you.

```bash
uv sync
cp .env.example .env
uv run python -c 'import secrets; print(secrets.token_hex())'   # paste this into SECRET_KEY in .env
uv run flask --app mafia_hustle run --debug
```

To play without setting up a real login, add some bots and turn on the developer login, which lets you play as any bot:

```bash
uv run flask --app mafia_hustle bots add
uv run flask --app mafia_hustle bots tick      # every bot takes a turn; run it whenever you like
DEV_LOGIN=1 uv run flask --app mafia_hustle run --debug
```

Then open **http://127.0.0.1:5000** (use `127.0.0.1`, not `localhost`: Bluesky's local-development login only redirects back to `127.0.0.1`).

`--debug` is for your machine only. Never run with debug mode on a public server.

## Running it in production

[`deploy/README.md`](deploy/README.md) has the full walkthrough. It covers a systemd service, a Caddy site block, and automatic deploys from GitHub whenever CI passes on `main`. The settings it uses:

| Variable | What it's for |
| --- | --- |
| `SECRET_KEY` | Signs login cookies. Required. The app refuses to start without it. |
| `PUBLIC_URL` | The public https address, e.g. `https://hustle.mkultra.monster`. Required for Bluesky logins, and turns on secure cookies. |
| `INSTANCE_PATH` | Folder for the SQLite database. Defaults to `instance/` next to the code. |
| `TRUST_PROXY` | Number of reverse proxies in front (usually `1`), so rate limits see real player IPs. |
| `DATABASE_URL` | Optional. Use a different database than SQLite. |
| `DEV_LOGIN` | `1` adds a page for logging in as a bot. Local testing only: the app refuses to start with it on an https `PUBLIC_URL`. |

## How the game works

- **Energy** pays for jobs and comes back one point a minute. **Stamina** pays for fights, one point every 2 minutes. **Health** comes back one point every 20 seconds, or all at once if you pay the doc.
- **Jobs** unlock as you level. Better jobs cost more energy and pay more. "Work the crowd" lifts cash from another player.
- **Fights** pit your attack against their defense, each with a random swing of 25% either way. Your best weapon, armor and ride count. Winners take part of the loser's cash.
- **Rackets** pay by the hour. Income piles up for 12 hours, then stops until you collect it.
- **The bank** keeps 10% of every deposit, and nobody can steal what's in it.
- **Skill points**: 3 per level, for attack, defense, max energy, max stamina or max health.
- **Bots** play by the same rules (see `mafia_hustle/bots.py` and "Bots" in [`deploy/README.md`](deploy/README.md)).

Everything you can do or buy lives in `mafia_hustle/catalog.py`, so balancing the game means editing numbers there. New player columns get added to an existing database automatically when the app starts (`upgrade_schema()` in `models.py`).

## How login works

- **Fediverse:** the game registers itself as an app on your instance (once per instance), sends you to your instance to approve, then asks `verify_credentials` who you are. It only requests `read:accounts`.
- **Bluesky / AT Protocol:** follows the [atproto OAuth spec](https://atproto.com/specs/oauth) (PAR, PKCE, DPoP) as a public client, asking only for the `atproto` scope, which proves who you are and grants nothing else.

Every request to a server you typed in goes through `mafia_hustle/oauth/safe_http.py`, which refuses private and internal addresses, redirects, and oversized responses, so the login form can't be used to poke at the server's own network.

## Development

```bash
uv run pytest            # tests
uv run pytest --cov      # tests with coverage
uv run ruff check .      # lint (includes security rules)
uv run ruff format .     # format
```

Game rules live in `mafia_hustle/rules.py` as plain functions with no Flask in them, so they're easy to test and tweak.

CI runs on every push and pull request: lint and format checks, tests on Python 3.11 to 3.14, a boot test under gunicorn, a dependency vulnerability audit, a secret scan of the full git history, and CodeQL. Dependabot opens weekly update PRs.

## Project layout

```
mafia_hustle/
  __init__.py      app factory and config
  models.py        players, what they own, their wire, logins; plus the schema upgrader
  catalog.py       jobs, gear and rackets (plain data)
  rules.py         game rules (no Flask)
  game.py          game pages and API
  bots.py          computer players and the `flask bots` commands
  auth.py          login and logout routes
  oauth/
    fediverse.py   Mastodon-API OAuth
    atproto.py     Bluesky / AT Protocol OAuth
    safe_http.py   locked-down HTTP client for talking to player-chosen servers
  templates/, static/
tests/
wsgi.py            entry point for gunicorn
```

## Ideas for later

- A hit list: put a bounty on someone
- Crews: team up with friends, and fight with your crew's numbers
- Job mastery: bonus rewards for doing the same job many times
