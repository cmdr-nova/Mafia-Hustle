# Hosting Mafia Hustle

This sets the game up at **https://hustle.mkultra.monster** on a Linux box that already runs Caddy. Everything stays out of the website's folder:

| What | Where |
| --- | --- |
| Code (a git checkout) | `/opt/mafia-hustle` |
| Database and the service user's home | `/var/lib/mafia-hustle` |
| Secrets and settings | `/etc/mafia-hustle/env` |
| The game itself | gunicorn on `127.0.0.1:8730`, not reachable from outside |

Caddy is the only thing facing the internet. It handles HTTPS and passes requests through to the game.

## One-time setup

Run these on the server.

**1. DNS.** Point `hustle.mkultra.monster` (A and/or AAAA record) at the box.

**2. A user for the game.** It owns the code and the database, and nothing else.

```bash
sudo useradd --system --create-home --home-dir /var/lib/mafia-hustle --shell /bin/bash mafia-hustle
```

**3. The code and its dependencies.**

```bash
sudo install -d -o mafia-hustle -g mafia-hustle /opt/mafia-hustle
sudo -u mafia-hustle git clone https://github.com/cmdr-nova/Mafia-Hustle /opt/mafia-hustle
sudo -u mafia-hustle -i sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
sudo -u mafia-hustle -i sh -c 'cd /opt/mafia-hustle && ~/.local/bin/uv sync --frozen --no-dev --extra prod'
```

**4. Settings.** Copy the example, then put a fresh secret key in it.

```bash
sudo install -d -m 750 -o root -g mafia-hustle /etc/mafia-hustle
sudo install -m 640 -o root -g mafia-hustle /opt/mafia-hustle/deploy/env.example /etc/mafia-hustle/env
python3 -c 'import secrets; print(secrets.token_hex())'   # paste into SECRET_KEY
sudo nano /etc/mafia-hustle/env
```

**5. Start the service.**

```bash
sudo cp /opt/mafia-hustle/deploy/mafia-hustle.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mafia-hustle
curl -sI http://127.0.0.1:8730/login | head -1   # expect: HTTP/1.1 200 OK
```

If port 8730 is already taken, change it in the service file, `Caddyfile.snippet`, and `deploy.sh`.

**6. Caddy.** Add the block from [`Caddyfile.snippet`](Caddyfile.snippet) to your Caddyfile and reload Caddy. Caddy gets the certificate on its own.

If Caddy came with the official PDS installer, it runs in Docker, and its Caddyfile is usually `/pds/caddy/etc/caddy/Caddyfile`. Check that the Caddy container uses host networking (`network_mode: host` in `/pds/compose.yaml`), so it can reach `127.0.0.1:8730`. Then restart it with `sudo docker restart caddy`.

Open https://hustle.mkultra.monster and log in. Done.

## Automatic deploys from GitHub

After this, every push to `main` that passes CI goes live on its own. GitHub connects over SSH with a key that can run **one** thing, `deploy/deploy.sh`. That script:

- takes a commit SHA as its argument
- refuses anything that isn't on `main`
- skips anything older than what's already running
- updates the code and dependencies
- reloads gunicorn without dropping requests
- fails if the site doesn't come back

**1. Make a key pair** on your own computer. No passphrase, because GitHub needs to use it unattended.

```bash
ssh-keygen -t ed25519 -N "" -C "mafia-hustle deploy" -f hustle_deploy
```

**2. Let that key in, restricted to the deploy script.** On the server:

```bash
sudo -u mafia-hustle -i sh -c 'install -d -m 700 ~/.ssh && touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
sudo -u mafia-hustle -i nano .ssh/authorized_keys
```

Add one line: the contents of `hustle_deploy.pub`, with this in front of it:

```
command="/opt/mafia-hustle/deploy/deploy.sh",restrict ssh-ed25519 AAAA... mafia-hustle deploy
```

`restrict` turns off shells, port forwarding, and everything else. If your `sshd_config` uses `AllowUsers` or `AllowGroups`, add `mafia-hustle` there.

**3. Add the secrets on GitHub.** Go to the repo's Settings → Secrets and variables → Actions → New repository secret.

| Secret | Value |
| --- | --- |
| `DEPLOY_HOST` | the server's hostname or IP |
| `DEPLOY_SSH_KEY` | the whole contents of `hustle_deploy` (the private key) |
| `DEPLOY_KNOWN_HOSTS` | the output of `ssh-keyscan -t ed25519 <server>`, run from a machine you trust |
| `DEPLOY_PORT` | only if SSH isn't on port 22 |

Then delete `hustle_deploy` from your computer. GitHub has the only copy it needs.

**4. Try it.** Go to Actions → Deploy → Run workflow. It should end with "Deployed <sha>."

### Rolling back

Revert the bad commit on `main` (`git revert`, or the Revert button on the PR). CI runs on the revert and the deploy ships it. The script won't deploy an older commit on purpose, so a revert is the way back.

## Bots

Bots are computer players: someone to fight, someone who robs you while you sleep, and a quick way to test changes. They can't log in, and they play by the same rules as everyone else. They show up with a "bot" tag in the game.

**Turn them on.** Create the crew once, then install the timer that gives each of them a turn every 5 minutes:

```bash
sudo -u mafia-hustle sh -c 'set -a; . /etc/mafia-hustle/env; cd /opt/mafia-hustle && .venv/bin/flask --app mafia_hustle bots add'
sudo cp /opt/mafia-hustle/deploy/mafia-hustle-bots.service /opt/mafia-hustle/deploy/mafia-hustle-bots.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mafia-hustle-bots.timer
```

**Check on them.**

```bash
systemctl list-timers mafia-hustle-bots.timer
sudo -u mafia-hustle sh -c 'set -a; . /etc/mafia-hustle/env; cd /opt/mafia-hustle && .venv/bin/flask --app mafia_hustle bots list'
```

**Turn them off.** Stop the timer, and optionally delete every bot along with everything they own:

```bash
sudo systemctl disable --now mafia-hustle-bots.timer
sudo -u mafia-hustle sh -c 'set -a; . /etc/mafia-hustle/env; cd /opt/mafia-hustle && .venv/bin/flask --app mafia_hustle bots remove'
```

## Day to day

```bash
journalctl -u mafia-hustle -f                 # live logs
sudo systemctl restart mafia-hustle           # full restart (after editing /etc/mafia-hustle/env)
sudo -u mafia-hustle sqlite3 /var/lib/mafia-hustle/mafia_hustle.db ".backup '/var/lib/mafia-hustle/backup.db'"
```
