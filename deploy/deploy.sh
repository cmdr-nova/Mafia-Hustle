#!/usr/bin/env bash
# Deploy one commit from main and reload the game without dropping requests.
#
# GitHub Actions runs this through an SSH key that can do nothing else (see deploy/README.md).
# To deploy by hand:
#   sudo -u mafia-hustle /opt/mafia-hustle/deploy/deploy.sh <full commit sha>
#
# Everything lives inside main() so bash reads the whole script before running it. That matters
# because the `git checkout` below replaces this very file.
set -euo pipefail

main() {
    local app_dir="${MAFIA_HUSTLE_DIR:-/opt/mafia-hustle}"
    local pidfile="${MAFIA_HUSTLE_PIDFILE:-/run/mafia-hustle/gunicorn.pid}"
    local health_url="${MAFIA_HUSTLE_HEALTH_URL:-http://127.0.0.1:8730/login}"
    local uv="${UV:-$HOME/.local/bin/uv}"
    command -v "$uv" >/dev/null || uv="$(command -v uv)"

    # Over SSH the commit arrives as the "command" the client asked to run.
    local sha="${SSH_ORIGINAL_COMMAND:-${1:-}}"
    if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
        echo "usage: deploy.sh <40-character commit sha>" >&2
        exit 2
    fi

    cd "$app_dir"
    git fetch --quiet origin main

    if ! git merge-base --is-ancestor "$sha" origin/main; then
        echo "Refusing to deploy $sha: it isn't on main." >&2
        exit 1
    fi

    local current
    current="$(git rev-parse HEAD)"
    if [[ "$current" != "$sha" ]] && git merge-base --is-ancestor "$sha" "$current"; then
        echo "Already running $current, which is newer than $sha. Nothing to do."
        exit 0
    fi

    git checkout --quiet --detach "$sha"
    "$uv" sync --frozen --no-dev --extra prod --quiet

    # SIGHUP makes gunicorn start fresh workers on the new code, then retire the old ones.
    kill -HUP "$(cat "$pidfile")"

    for _ in $(seq 1 20); do
        if curl -fsS -o /dev/null "$health_url"; then
            echo "Deployed $sha."
            exit 0
        fi
        sleep 1
    done
    echo "Deployed $sha, but $health_url isn't answering. Check: journalctl -u mafia-hustle" >&2
    exit 1
}

main "$@"
