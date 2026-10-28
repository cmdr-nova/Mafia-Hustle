# Mafia Hustle

A small browser game in the spirit of Mafia Wars. Run jobs, rob people, attack players on the leaderboard, level up to 60, then prestige forever.

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

Then open **http://127.0.0.1:5000** (use `127.0.0.1`, not `localhost`: Bluesky's local-development login only redirects back to `127.0.0.1`).

`--debug` is for your machine only. Never run with debug mode on a public server.

## Running it in production

Set these in the environment (or `.env`):

| Variable | What it's for |
| --- | --- |
| `SECRET_KEY` | Signs login cookies. Required. The app refuses to start without it. |
| `PUBLIC_URL` | The public https address, e.g. `https://hustle.example.com`. Required for Bluesky logins, and turns on secure cookies. |
| `DATABASE_URL` | Optional. Defaults to SQLite in `instance/`. |

Then run it with gunicorn behind your reverse proxy:

```bash
uv sync --extra prod
uv run gunicorn --bind 127.0.0.1:8000 wsgi:app
```

Bluesky servers fetch `PUBLIC_URL/oauth/client-metadata.json` to learn about the app, so that URL has to be reachable from the internet.

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
  models.py        players, registered fediverse apps, in-progress logins
  rules.py         game rules (no Flask)
  game.py          game pages and API
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

- Energy and stamina that regenerate over time, so every action is a choice
- Weapons, armor, and properties to spend money on
- Fights decided by attack and defense stats plus a roll
- A hit list, crews, and a combat log
