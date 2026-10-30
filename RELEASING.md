# Versions and releases

## Deploys and releases are different things

Every merge to `main` deploys to https://hustle.mkultra.monster as soon as CI passes. That doesn't change.

A **release** is a named checkpoint on top of that: a version number, a git tag like `v0.3.0`, and a GitHub release with notes from [CHANGELOG.md](CHANGELOG.md). It tells players and you what changed and when, and gives a known-good point to compare against when something breaks. Releasing never deploys anything, because by the time you release, that code is already live.

## Version numbers

Versions follow [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`. The version lives in one place, `pyproject.toml`.

While the game is below 1.0:

| Bump | When | Examples |
| --- | --- | --- |
| **Minor** (0.3.0 → 0.4.0) | New things to do, or changes players will clearly notice | new jobs, items or systems; a redesign; database changes; changes to how login works; a big rebalance |
| **Patch** (0.3.0 → 0.3.1) | Fixes and small tweaks | bug fixes, security fixes, small number tweaks in `catalog.py`, copy changes |
| None | Nothing players or the server would notice | tests, CI, docs, routine Dependabot updates |

**1.0.0** is the point where you're happy to tell strangers to play, and you're promising not to wipe their progress. After that, a **major** bump (2.0.0) means something that breaks that promise or forces players to do something: a reset or wipe, dropping a login method, removing a feature people rely on.

## When to cut a release

- **After every minor change.** When a PR that adds features merges, release it the same day.
- **Right away for security fixes.** Once the fix is live, cut a patch release, then publish the security advisory (see [SECURITY.md](SECURITY.md)).
- **When fixes pile up.** If there are unreleased patch-level changes and it's been about two weeks, or there are five or more, cut a patch release.
- **Never on a red `main`.** The Release workflow refuses a commit that CI hasn't passed on.

## In every PR

If the change is something players or the server would notice, add a line to the **Unreleased** section of [CHANGELOG.md](CHANGELOG.md), under the right heading: Added, Changed, Fixed, Removed, or Security. Write it for a player, not a programmer.

## How to cut a release

1. **Open a release PR.** On a new branch, bump the version. uv updates both `pyproject.toml` and `uv.lock`:

   ```bash
   uv version --bump minor    # or: uv version --bump patch
   ```

   Then in `CHANGELOG.md`, rename `## [Unreleased]` to `## [0.4.0] - 2026-11-14` (the new version and today's date), add a fresh empty `## [Unreleased]` above it, and update the compare links at the bottom of the file.

2. **Merge it.** CI runs, and the deploy goes out like any other merge.

3. **Publish.** On GitHub go to **Actions → Release → Run workflow** and click **Run workflow**. Leave the commit empty to release the latest `main`. The workflow checks that CI passed, that the version isn't released yet, and that the changelog has notes for it. Then it creates the tag and the GitHub release.

A test (`tests/test_release.py`) fails if `pyproject.toml` has a version that `CHANGELOG.md` doesn't mention, so step 1 can't be half done.

## Rolling back

`deploy.sh` won't deploy a commit older than what's running, so rolling back means reverting: revert the bad PR on GitHub, merge the revert, and it deploys. If the bad change was already released, ship the revert as a patch release.

## Releasing an older commit

The **commit** box on the Release workflow takes any commit on `main`, and uses the version in that commit's `pyproject.toml`. The notes still come from the current `CHANGELOG.md`. Release older versions before newer ones, so GitHub marks the newest as **Latest**.

The first two releases go in this way, oldest first:

| Version | Commit |
| --- | --- |
| v0.2.0 | `8568840` (merge of PR #2) |
| v0.3.0 | `fed2138` (merge of PR #3) |
