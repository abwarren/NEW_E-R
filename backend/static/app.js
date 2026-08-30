/* E&R PokerBet — remote fleet-control dashboard.
 * REMOTE → PLAYERS → BROWSER → TABLE → HAND. Every player independently
 * controllable; commands route by full identity chain (player/browser/table/
 * hand) and can never cross players (server-enforced). SSE live.
 */
const $ = (id) => document.getElementById(id);
const API_KEY = window.localStorage.getItem('er_api_key') || '';
const H = { 'X-API-Key': API_KEY, 'Content-Type': 'application/json' };

function fmtTime(iso) { return new Date(iso).toLocaleTimeString(); }
function clock() { $('clock').textContent = new Date().toLocaleTimeString(); }
setInterval(clock, 1000);

function cardHtml(cards) {
  if (!cards || !cards.length) return '<span class="muted">—</span>';
  return '<span class="cards">' + cards.join(' ') + '</span>';
}

// a player is ONLINE if any of their tables has fresh snapshots
function playerStatus(tables) {
  return tables.some(t => !t.is_stale)
    ? '<span class="live">🟢 ONLINE</span>'
    : '<span class="stale">🔴 OFFLINE</span>';
}

// ── fleet render: group tables by player (REMOTE → PLAYER → TABLE) ───────
function renderFleet(rows) {
  const root = $('fleet');
  if (!rows.length) {
    root.innerHTML = '<div class="muted">no tables yet — waiting for snapshots…</div>';
    return;
  }
  const byPlayer = {};
  rows.forEach(t => {
    (byPlayer[t.player_id] = byPlayer[t.player_id] || []).push(t);
  });
  root.innerHTML = Object.keys(byPlayer).map(pid => `
    <div class="player-block">
      <div class="player-head">👤 ${pid} <span class="muted">(${byPlayer[pid].length} table${byPlayer[pid].length > 1 ? 's' : ''})</span> ${playerStatus(byPlayer[pid])}</div>
      ${byPlayer[pid].map(t => tableCard(t)).join('')}
    </div>`).join('');
}

function tableCard(t) {
  const actions = (t.available_actions || []).map(a => actionBtn(t, a)).join('') ||
    '<span class="muted">no actions available</span>';
  return `
    <div class="table-card ${t.is_stale ? 'stale' : ''}">
      <div class="table-head">
        <span class="badge street">${t.street || '—'}</span>
        <b>Table ${t.table_id}</b>
        <span class="muted">hand ${t.hand_id || '—'}</span>
        <span class="muted">browser ${t.browser_instance_id}</span>
        <span class="${t.is_stale ? 'stale' : 'live'}">${t.is_stale ? '🔴 STALE' : '🟢 live'}</span>
        <span class="muted">last ${fmtTime(t.updated_at)} · v${t.snapshot_version}</span>
      </div>
      <div class="table-body">
        <div class="table-meta">
          <span>hero: <b>${t.hero_name || '—'}</b> seat ${t.hero_seat >= 0 ? t.hero_seat : '—'}</span>
          <span>pot: <b>R${t.pot.toFixed ? t.pot.toFixed(2) : t.pot}</b></span>
          <span>board: ${cardHtml(t.board)}</span>
        </div>
        <div class="table-controls">
          <span class="muted" style="font-size:11px">remote control →</span>
          ${actions}
        </div>
      </div>
    </div>`;
}

function actionBtn(t, action) {
  return `<button class="btn act ${action}" data-p="${t.player_id}" data-b="${t.browser_instance_id}" data-t="${t.table_id}" data-h="${t.hand_id}" data-a="${action}">${action.toUpperCase()}</button>`;
}

// ── command issuance (routed by full identity chain) ─────────────────────
async function issueCommand(btn) {
  const body = {
    player_id: btn.dataset.p,
    browser_instance_id: btn.dataset.b,
    table_id: btn.dataset.t,
    hand_id: btn.dataset.h,
    action: btn.dataset.a,
  };
  btn.disabled = true;
  try {
    const r = await fetch('/api/commands', { method: 'POST', headers: H, body: JSON.stringify(body) });
    const res = await r.json();
    logLine(`CMD ${body.player_id} @${body.table_id} ${body.action} → ${r.ok ? 'QUEUED ' + res.command_id : 'ERR ' + (res.detail || r.status)}`);
  } catch (e) {
    logLine('CMD failed: ' + e);
  } finally {
    setTimeout(() => { btn.disabled = false; }, 800);
  }
}
$('fleet').addEventListener('click', (e) => {
  const btn = e.target.closest('button.act');
  if (btn) issueCommand(btn);
});

async function refresh() {
  try {
    const r = await fetch('/api/tables', { headers: H });
    if (r.ok) renderFleet(await r.json());
  } catch (e) { /* backend not up yet */ }
}

function logLine(text) {
  const div = document.createElement('div');
  div.textContent = '[' + new Date().toLocaleTimeString() + '] ' + text;
  $('log').prepend(div);
  while ($('log').children.length > 80) $('log').lastChild.remove();
}

function connectSSE() {
  const es = new EventSource('/api/events' + (API_KEY ? '?x_api_key=' + API_KEY : ''));
  const conn = $('conn');
  es.onopen = () => { conn.textContent = '● live'; conn.className = 'live'; };
  es.onerror = () => { conn.textContent = '○ reconnecting…'; conn.className = ''; };
  es.onmessage = (e) => {
    try {
      const m = JSON.parse(e.data);
      if (m.type === 'table' || m.type === 'equity' || m.type === 'command') refresh();
      if (m.type !== 'keepalive') logLine((m.type || 'event') + ' ' + (m.scope || '') + ' ' + JSON.stringify(m.payload || {}).slice(0, 120));
    } catch (_) { /* keepalive */ }
  };
}

// ── equity panel (directional cards, per-hero) ───────────────────────────
$('eq-run').addEventListener('click', async () => {
  let hands, board;
  try {
    hands = JSON.parse($('eq-hands').value);
    board = JSON.parse($('eq-board').value || '[]');
  } catch (e) { $('eq-result').textContent = 'invalid JSON input'; return; }
  const out = $('eq-result');
  out.innerHTML = 'calculating…';
  try {
    const r = await fetch('/api/equity', { method: 'POST', headers: H, body: JSON.stringify({ variant: 'plo', hands, board, samples: 2000 }) });
    const res = await r.json();
    if (res.error) { out.textContent = 'error: ' + res.error; return; }
    const byHero = {};
    res.results.forEach(x => { (byHero[x.hero_index] = byHero[x.hero_index] || []).push(x); });
    out.innerHTML = Object.keys(byHero).map(hi => `
      <div class="hero-block">
        <div class="hero-title">HERO ${hands[hi].join(' ')}</div>
        ${byHero[hi].map(x => `
          <div class="eq-card">
            <div class="eq-card-head">${hands[x.hero_index].join(' ')} → ${hands[x.villain_index].join(' ')}</div>
            <div class="eq-row"><span>Raw</span><b>${x.raw_equity}%</b></div>
            <div class="eq-row"><span>Realized</span><b>${x.realized_equity}%</b></div>
            <div class="eq-row ${x.disparity < 0 ? 'neg' : 'pos'}"><span>Disparity</span><b>${x.disparity >= 0 ? '+' : ''}${x.disparity}%</b></div>
          </div>`).join('')}
      </div>`).join('');
  } catch (e) { out.textContent = 'request failed: ' + e; }
});

refresh();
setInterval(refresh, 5000); // slow fallback only; SSE is primary
connectSSE();
