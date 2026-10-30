# Security policy

Thanks for looking. Mafia Hustle is a small hobby game, but it signs people in with their real fediverse and Bluesky accounts, so security reports are taken seriously.

## Reporting a vulnerability

**Please report privately, not in a public issue or pull request.**

Use GitHub's private reporting: [open a security advisory](https://github.com/cmdr-nova/Mafia-Hustle/security/advisories/new) (or go to the repo's **Security** tab and click **Report a vulnerability**). Only the maintainer can see it.

Helpful things to include:

- what the problem is and what an attacker could do with it
- steps to reproduce, or a proof of concept
- the commit or version you tested against
- whether you tested on the live game or a local copy

## What to expect

This is run by one person in their spare time, so these are goals, not guarantees:

- an acknowledgement within **7 days**
- a first assessment (is it real, how bad is it) within **14 days**
- a fix for serious issues as soon as it's practical; anything that exposes player accounts or the server comes first

Fixes merged to `main` deploy to the live game automatically once CI passes. After that a patch release goes out (see [RELEASING.md](RELEASING.md)), and the advisory is published with credit to you, unless you'd rather stay anonymous.

## Supported versions

Only the latest release, and the code currently on `main` (which is what runs at https://hustle.mkultra.monster), get security fixes. There are no long-lived release branches.

## In scope

- this repository's code, workflows and deploy scripts
- the live game at https://hustle.mkultra.monster

Things that would be especially bad, and worth a close look:

- logging in as someone else, or forging a session cookie
- the fediverse or Bluesky login flows (OAuth, PKCE, DPoP, state handling)
- making the server send requests to private or internal addresses through the login form (`mafia_hustle/oauth/safe_http.py` is meant to stop this)
- reading or changing another player's data
- getting code to run on the server, or getting at its secrets
- the GitHub Actions workflows, especially anything that could reach the deploy key

## Out of scope

- denial of service, load testing, or anything that floods the live server
- spam, social engineering, or physical attacks
- bugs in Mastodon, GoToSocial, Bluesky or other servers the game talks to (report those upstream)
- other sites and services on the same host
- missing hardening headers or best practices with no demonstrated impact
- game balance exploits that only affect your own account, like a way to farm cash faster. Those are welcome as normal issues

## Testing on the live game

Please be gentle with it. Use your own accounts, don't access or change other players' data beyond the minimum needed to show the problem, don't run automated scanners against it, and stop and report as soon as you've confirmed an issue. A local copy (see the README) is usually the better place to dig. Research done in good faith along these lines is welcome, and won't be met with legal threats.

## What the game stores

For each player: which fediverse or Bluesky account they are (account id and handle), and their game stats. No passwords, emails, or login tokens are kept. Tokens are revoked as soon as the game knows who you are.
