// Everything shown here that came from another player (names, handles) goes through
// textContent, never innerHTML, so nobody can inject markup with a crafted name.

const csrfToken = document.querySelector('meta[name="csrf-token"]').content;

async function post(url, body = {}) {
    const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({ error: 'Something went wrong.' }));
    log(data.message || data.error);
    await refresh();
}

function log(text) {
    const item = document.createElement('li');
    item.className = 'list-group-item small';
    item.textContent = text;
    document.getElementById('action-log').prepend(item);
}

async function refreshStats() {
    const data = await (await fetch('/api/player-info')).json();
    const stats = document.getElementById('stats');
    stats.replaceChildren();
    const rows = [
        ['Health', `${data.health} / ${data.max_health}`],
        ['Money', `$${data.money}`],
        ['Level', data.level],
        ['Points', `${data.points} / ${data.points_needed}`],
        ['Kills', data.kills],
        ['Prestige', data.prestige],
    ];
    for (const [label, value] of rows) {
        const dt = document.createElement('dt');
        dt.className = 'col-6';
        dt.textContent = label;
        const dd = document.createElement('dd');
        dd.className = 'col-6';
        dd.textContent = value;
        stats.append(dt, dd);
    }
}

async function refreshLeaderboard() {
    const data = await (await fetch('/api/leaderboard')).json();
    const list = document.getElementById('leaderboard');
    list.replaceChildren();
    for (const player of data.leaderboard) {
        const item = document.createElement('li');
        item.className = 'list-group-item d-flex justify-content-between align-items-center gap-2';

        const label = document.createElement('span');
        label.className = 'text-break';
        label.textContent = `${player.username} · Lv ${player.level} · ${player.kills} kills`;
        if (!player.alive) label.classList.add('text-decoration-line-through', 'text-body-secondary');
        item.append(label);

        if (player.id !== window.CURRENT_USER_ID && player.alive) {
            const button = document.createElement('button');
            button.className = 'btn btn-sm btn-outline-danger';
            button.textContent = 'Attack';
            button.addEventListener('click', () => post('/api/attack', { defender_id: player.id }));
            item.append(button);
        }
        list.append(item);
    }
}

function refresh() {
    return Promise.all([refreshStats(), refreshLeaderboard()]);
}

document.getElementById('run-job-btn').addEventListener('click', () => post('/api/run-job'));
document.getElementById('heal-up-btn').addEventListener('click', () => post('/api/heal-up'));
refresh();
