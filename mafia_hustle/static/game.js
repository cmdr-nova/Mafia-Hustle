// Everything shown here that came from another player (names, handles) goes through
// textContent, never innerHTML, so nobody can inject markup with a crafted name.

const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const $ = (id) => document.getElementById(id);
const fmt = (n) => '$' + n.toLocaleString('en-US');
let state = null;

// Build an element: h('div', { className: 'x', onclick: fn }, 'text', otherElement)
function h(tag, props = {}, ...children) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
        if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
        else if (key === 'dataset') Object.assign(el.dataset, value);
        else if (value !== undefined && value !== null && value !== false) el[key] = value;
    }
    for (const child of children.flat()) {
        if (child === null || child === undefined || child === false) continue;
        el.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return el;
}

// --- Talking to the server ---------------------------------------------------------------------

async function getJSON(url) {
    const response = await fetch(url, { headers: { Accept: 'application/json' } });
    if (response.status === 401 || response.redirected) {
        window.location = '/login';
        throw new Error('Logged out');
    }
    return response.json();
}

async function act(name, body = {}, button = null) {
    if (button) button.disabled = true;
    try {
        const response = await fetch(`/api/do/${name}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify(body),
        });
        const data = await response.json().catch(() => ({ error: 'Something went wrong.' }));
        const ok = response.ok && data.ok !== false;
        say(data.message || data.error, ok ? 'good' : 'bad');
        if (data.state) render(data.state);
        if (name === 'attack' || name === 'job') refreshBoards();
    } finally {
        if (button) button.disabled = false;
    }
}

async function refreshState() {
    render(await getJSON('/api/state'));
}

async function refreshBoards() {
    const [targets, board] = await Promise.all([
        getJSON('/api/targets'),
        getJSON('/api/leaderboard'),
    ]);
    renderTargets(targets.targets);
    renderLeaderboard(board.leaderboard, board.me);
}

// --- The Wire and toasts -----------------------------------------------------------------------

const seenEvents = new Set();
let toastTimer;

function wireItem(text, kind, when = new Date()) {
    const item = h('li', { className: `${kind} fresh` },
        h('time', { dateTime: when.toISOString() }, when.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })),
        text);
    $('wire').prepend(item);
    while ($('wire').children.length > 40) $('wire').lastChild.remove();
}

function say(text, kind) {
    wireItem(text, kind);
    const toast = $('toast');
    toast.textContent = text;
    toast.className = `toast show ${kind === 'bad' ? 'bad' : ''}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 3500);
}

function renderEvents(events) {
    // Oldest first, so the newest ends up on top.
    for (const event of [...events].reverse()) {
        if (seenEvents.has(event.id)) continue;
        seenEvents.add(event.id);
        wireItem(event.text, 'news', new Date(event.at));
    }
}

// --- Status strip ------------------------------------------------------------------------------

const BAR_LABELS = { health: 'Health', energy: 'Energy', stamina: 'Stamina' };

function clock(seconds) {
    const m = Math.floor(seconds / 60);
    const s = String(seconds % 60).padStart(2, '0');
    return `${m}:${s}`;
}

function renderMeter(el, label, value, max, note) {
    const pct = max ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
    el.replaceChildren(
        h('div', { className: 'top' }, h('span', {}, label), h('b', { className: 'num' }, `${value} / ${max}`)),
        h('div', { className: 'track' }, h('div', { className: 'fill', style: `width:${pct}%` })),
        h('div', { className: 'next num' }, note || ''),
    );
}

function renderBars() {
    for (const [bar, info] of Object.entries(state.bars)) {
        const note = info.next_in === null ? 'Full' : `+1 in ${clock(info.next_in)}`;
        renderMeter($(`bar-${bar}`), BAR_LABELS[bar], info.value, info.max, note);
    }
    const health = state.bars.health;
    $('bar-health').classList.toggle('low', health.value < health.max * 0.3);
}

function renderStatus() {
    const p = state.player;
    renderBars();
    $('cash').textContent = fmt(p.money);
    $('bank').textContent = fmt(p.bank);
    $('level').textContent = p.level;
    renderMeter($('bar-xp'), p.prestige ? `Prestige ${p.prestige}` : 'Experience', p.points, p.points_needed, '');
    const pill = $('points-pill');
    pill.hidden = !p.skill_points;
    pill.textContent = `${p.skill_points} skill point${p.skill_points === 1 ? '' : 's'}`;
}

// Count the regen timers down locally, and ask the server again once one runs out.
setInterval(() => {
    if (!state) return;
    let due = false;
    for (const info of Object.values(state.bars)) {
        if (info.next_in === null) continue;
        info.next_in = Math.max(0, info.next_in - 1);
        if (info.next_in === 0) due = true;
    }
    renderBars();
    if (due) refreshState();
}, 1000);

// --- Panels ------------------------------------------------------------------------------------

function chip(kind, text) {
    return h('span', { className: `chip ${kind}` }, text);
}

function renderJobs() {
    const p = state.player;
    $('jobs').replaceChildren(...state.jobs.map((job) => {
        const locked = p.level < job.min_level;
        const pay = job.robbery ? 'Steals cash' : `${fmt(job.payout[0])} to ${fmt(job.payout[1])}`;
        return h('article', { className: `item ${locked ? 'locked' : ''}` },
            h('h3', {}, job.name),
            h('p', { className: 'blurb' }, job.blurb),
            h('div', { className: 'chips' },
                chip('energy', `${job.energy} energy`),
                chip('money', pay),
                chip('points', `+${job.points} pts`)),
            h('div', { className: 'spacer' }),
            locked
                ? h('button', { className: 'btn btn-block', disabled: true }, `Unlocks at level ${job.min_level}`)
                : h('button', {
                    className: 'btn btn-brass btn-block',
                    disabled: state.bars.energy.value < job.energy,
                    onclick: (e) => act('job', { job: job.key }, e.currentTarget),
                }, 'Do the job'));
    }));
}

function renderShop() {
    const p = state.player;
    const slots = { weapon: 'Weapons', armor: 'Armor', ride: 'Rides' };
    const sections = [];
    for (const [slot, title] of Object.entries(slots)) {
        sections.push(h('h3', { className: 'slot-title' }, title));
        sections.push(h('div', { className: 'grid' }, state.gear.filter((g) => g.slot === slot).map((g) => {
            const locked = p.level < g.min_level;
            const equipped = state.loadout[slot] === g.key;
            let button;
            if (g.owned) button = h('button', { className: 'btn btn-block', disabled: true }, 'Owned');
            else if (locked) button = h('button', { className: 'btn btn-block', disabled: true }, `Unlocks at level ${g.min_level}`);
            else button = h('button', {
                className: 'btn btn-brass btn-block',
                disabled: p.money < g.price,
                onclick: (e) => act('buy', { item: g.key }, e.currentTarget),
            }, `Buy for ${fmt(g.price)}`);
            return h('article', { className: `item ${locked && !g.owned ? 'locked' : ''} ${g.owned ? 'owned' : ''}` },
                equipped ? h('span', { className: 'tag equipped' }, 'In use') : g.owned ? h('span', { className: 'tag' }, 'Owned') : null,
                h('h3', {}, g.name),
                h('div', { className: 'chips' }, chip('attack', `+${g.attack} attack`), chip('defense', `+${g.defense} defense`)),
                h('div', { className: 'spacer' }),
                button);
        })));
    }
    $('shop').replaceChildren(...sections);
}

function renderRackets() {
    const p = state.player;
    const income = state.income;
    $('income-text').textContent = income.per_hour
        ? `Your rackets bring in ${fmt(income.per_hour)} an hour.`
        : 'Buy a front and it pays you every hour, even while you sleep.';
    $('uncollected').textContent = `${fmt(income.uncollected)} waiting`;
    $('cap-text').textContent = `Income piles up for ${income.cap_hours} hours, then stops until you collect.`;
    $('collect-btn').disabled = !income.uncollected;
    $('rackets').replaceChildren(...state.rackets.map((r) => {
        const locked = p.level < r.min_level;
        return h('article', { className: `item ${locked ? 'locked' : ''} ${r.owned ? 'owned' : ''}` },
            r.owned ? h('span', { className: 'tag' }, `× ${r.owned}`) : null,
            h('h3', {}, r.name),
            h('p', { className: 'blurb' }, r.blurb),
            h('div', { className: 'chips' }, chip('money', `${fmt(r.income)} / hour`)),
            h('div', { className: 'spacer' }),
            locked
                ? h('button', { className: 'btn btn-block', disabled: true }, `Unlocks at level ${r.min_level}`)
                : h('button', {
                    className: 'btn btn-brass btn-block',
                    disabled: p.money < r.price,
                    onclick: (e) => act('buy', { item: r.key }, e.currentTarget),
                }, `Buy for ${fmt(r.price)}`));
    }));
}

function renderFightPanel() {
    const p = state.player;
    $('power-attack').textContent = p.attack;
    $('power-defense').textContent = p.defense;
    const cost = state.hospital_cost;
    $('doc-text').textContent = cost
        ? `Patch you up to full for ${fmt(cost)}. Health also comes back on its own, slowly.`
        : "You're in one piece. Come back after the next fight.";
    $('hospital-btn').disabled = !cost || p.money < cost;
}

function renderBank() {
    const p = state.player;
    $('vault-cash').textContent = fmt(p.money);
    $('vault-bank').textContent = fmt(p.bank);
    $('bank-text').textContent = `Cash in the vault can't be stolen. The banker keeps ${state.bank_fee_percent}% of every deposit.`;
}

function renderProfile() {
    const p = state.player;
    const rows = [
        ['Level', p.level], ['Prestige', p.prestige],
        ['Base attack', p.base_attack], ['Base defense', p.base_defense],
        ['Max energy', state.bars.energy.max], ['Max stamina', state.bars.stamina.max],
        ['Max health', state.bars.health.max], ['Jobs done', p.jobs_done.toLocaleString()],
        ['Fights won', p.fights_won], ['Fights lost', p.fights_lost], ['Kills', p.kills],
    ];
    $('stats').replaceChildren(...rows.map(([k, v]) => h('div', {}, h('dt', {}, k), h('dd', { className: 'num' }, v))));
    $('skill-text').textContent = p.skill_points
        ? `You have ${p.skill_points} skill point${p.skill_points === 1 ? '' : 's'} to spend.`
        : 'You get 3 skill points every level.';
    $('skills').replaceChildren(...Object.entries(state.skills).map(([key, label]) =>
        h('button', {
            className: 'btn',
            disabled: !p.skill_points,
            onclick: (e) => act('skill', { skill: key }, e.currentTarget),
        }, label)));
    document.querySelector('[data-tab="profile"]').replaceChildren('Profile', p.skill_points ? h('span', { className: 'dot' }) : '');
}

function render(newState) {
    state = newState;
    renderStatus();
    renderJobs();
    renderFightPanel();
    renderShop();
    renderRackets();
    renderBank();
    renderProfile();
    renderEvents(state.events);
}

// --- Players -----------------------------------------------------------------------------------

function monogram(player) {
    const words = (player.display_name || player.username).replace(/[^\p{L}\p{N} ]/gu, '').trim().split(/\s+/);
    const letters = (words[0]?.[0] || '?') + (words.length > 1 ? words[words.length - 1][0] : '');
    const hue = (player.id * 47) % 360;
    return h('span', { className: 'monogram', style: `background:hsl(${hue} 45% 62%)`, ariaHidden: 'true' }, letters.toUpperCase());
}

function playerName(player) {
    return h('div', { className: 'handle' }, player.display_name || player.username,
        player.bot ? h('span', { className: 'bot-tag' }, 'bot') : null);
}

function renderTargets(targets) {
    if (!targets.length) {
        $('targets').replaceChildren(h('li', { className: 'empty' }, 'Nobody on the street right now.'));
        return;
    }
    const canFight = state && state.bars.stamina.value > 0;
    $('targets').replaceChildren(...targets.map((t) =>
        h('li', { className: 'row' },
            monogram(t),
            h('div', { className: 'who-col' },
                playerName(t),
                h('div', { className: 'sub' }, `Level ${t.level} · ${t.fights_won} fights won · ${t.kills} kills`)),
            h('button', {
                className: 'btn btn-red btn-sm',
                disabled: !canFight,
                title: canFight ? '' : 'Out of stamina',
                onclick: (e) => act('attack', { defender_id: t.id }, e.currentTarget),
            }, 'Jump them'))));
}

function leaderRow(p, rank) {
    const mine = p.id === window.CURRENT_USER_ID;
    return h('li', { className: `row ${p.alive ? '' : 'dead'} ${mine ? 'me' : ''}` },
        h('span', { className: 'rank' }, rank),
        monogram(p),
        h('div', { className: 'who-col' },
            playerName(p),
            h('div', { className: 'sub' }, `Level ${p.level} · ${p.kills} kills`)));
}

function renderLeaderboard(players, me) {
    const rows = players.map((p, i) => leaderRow(p, i + 1));
    // Outside the top 10? Pin your own spot underneath so you know where you stand.
    if (me) rows.push(h('li', { className: 'gap', ariaHidden: 'true' }, '⋯'), leaderRow(me, me.rank));
    $('leaderboard').replaceChildren(...rows);
}

// --- Tabs and forms ----------------------------------------------------------------------------

function showTab(name) {
    for (const tab of document.querySelectorAll('.tab')) {
        const selected = tab.dataset.tab === name;
        tab.setAttribute('aria-selected', selected);
        $(`tab-${tab.dataset.tab}`).hidden = !selected;
    }
    try { localStorage.setItem('tab', name); } catch { /* private mode */ }
}

for (const tab of document.querySelectorAll('.tab')) {
    tab.addEventListener('click', () => showTab(tab.dataset.tab));
}
let savedTab = 'jobs';
try { savedTab = localStorage.getItem('tab') || 'jobs'; } catch { /* private mode */ }
showTab(document.querySelector(`[data-tab="${savedTab}"]`) ? savedTab : 'jobs');

$('points-pill').addEventListener('click', () => showTab('profile'));
$('hospital-btn').addEventListener('click', (e) => act('hospital', {}, e.currentTarget));
$('collect-btn').addEventListener('click', (e) => act('collect', {}, e.currentTarget));
$('reshuffle').addEventListener('click', refreshBoards);

$('bank-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const amount = parseInt($('amount').value, 10);
    if (!amount || amount < 1) return say('Enter an amount first.', 'bad');
    act('bank', { direction: e.submitter.dataset.direction, amount }, e.submitter);
    $('amount').value = '';
});
$('deposit-all').addEventListener('click', (e) => {
    if (state && state.player.money > 0) act('bank', { direction: 'deposit', amount: state.player.money }, e.currentTarget);
});

// Keep the wire and boards fresh while the tab is open.
setInterval(() => { if (!document.hidden) { refreshState(); refreshBoards(); } }, 30000);

refreshState().then(refreshBoards);
