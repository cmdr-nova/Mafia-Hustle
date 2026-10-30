# Changelog

Notable changes to Mafia Hustle. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/). [RELEASING.md](RELEASING.md) says what counts as a minor or patch change and when to cut a release.

Every PR that changes something players or the server would notice adds a line under **Unreleased**.

## [Unreleased]

### Added

- A security policy ([SECURITY.md](SECURITY.md)) with a private way to report vulnerabilities.
- This changelog, release rules ([RELEASING.md](RELEASING.md)), and a Release workflow that tags a version and publishes its GitHub release.

### Changed

- The README leads with the hat logo, a link to the live game, and screenshots.
- Bots retire once they pass level 5, and a new level 1 bot with a fresh name takes their place, so they never outgrow new players. They also stop jumping people more than a level below them.

## [0.3.0] - 2026-10-30

### Added

- Energy, stamina and health that regenerate over time.
- A job ladder that unlocks by level, a shop of weapons, armor and rides, fights decided by attack against defense plus gear and a roll, rackets that pay by the hour, a bank, and skill points on level-up.
- A wire that tells you when someone jumped or robbed you.
- Bots that play by the same rules, managed with `flask bots add|tick|list|remove`, plus a systemd timer to run them on the server.
- A local-only developer login for playing as a bot.
- A hat favicon.

### Changed

- New noir look: custom stylesheet with self-hosted fonts, no Bootstrap or other CDN.
- The database upgrades itself on startup. Missing columns are added, and existing players get the skill points their levels already earned.

### Fixed

- Two quick clicks, or a player and a bot acting at once, can no longer spend the same money twice.

## [0.2.0] - 2026-10-30

### Added

- Login with a fediverse account (anything that speaks the Mastodon API) or a Bluesky / AT Protocol account. The game never sees or stores a password.
- CI: lint, tests on Python 3.11 to 3.14, a boot test, a dependency audit, a secret scan, and CodeQL. Dependabot opens weekly update PRs.
- Rate limits on game actions and login.
- A deploy kit (systemd service, Caddy block) and automatic deploys to the live server after CI passes on `main`.

### Changed

- Restructured into a Python package that installs with uv and has tests.
- SQLite runs in WAL mode, and job targets are picked in SQL, so the game holds up with many players.

### Removed

- Username and password login.

### Security

- Removed a committed secret key, a local database and uploads from the repository.
- The app refuses to start without a `SECRET_KEY`.
- Requests to servers a player types in go through a guard that blocks private and internal addresses.

## Before 0.2.0

The original tutorial-era game, with username and password login. Never versioned or released.

[Unreleased]: https://github.com/cmdr-nova/Mafia-Hustle/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/cmdr-nova/Mafia-Hustle/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/cmdr-nova/Mafia-Hustle/releases/tag/v0.2.0
