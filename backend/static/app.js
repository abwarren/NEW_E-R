/* E&R PokerBet dashboard client — SSE live, no polling. */
const $ = (id) => document.getElementById(id);
const API_KEY = window.localStorage.getItem('er_api_key') || '';
const H = { 'X-API-Key': API_KEY, 'Content-Type': 'application/json' };

function fmtTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString();
}
function clock() { $('clock').textContent = new Date().toLocaleTimeString(); }
setInterval(clock, 1000);

function cardHtml(cards) {
  if (!cards || !cards.length) return '<span class="muted">—</span>';
  return '<span class="cards">' + cards.join(' ') + '</span>';
}

function renderTables(rows) {
  const tb = $('tbody');
  if (!rows.length) { tb.innerHTML = '<tr><td colspan="10" class="muted">no tables yet — waiting for snapshots…</td></tr>'; return; }
  tb.innerHTML = rows.map(t => `
    <tr class="${t.is_stale ? 'stale' : ''}">
      <td class="muted">${t.player_id}<br>${t.browser_instance_id}</td>
      <td>${t.table_id}</td>
      <td>${t.hand_id || '—'}</td>
      <td><span class="badge street">${t.street || '—'}</span></td>
      <td>${t.hero_seat >= 0 ? t.hero_name + ' <span class="badge hero">seat ' + t.hero_seat + '</span>' : '—'}</td>
      <td>R${t.pot.toFixed ? t.pot.toFixed(2) : t.pot}</td>
      <td>${cardHtml(t.board)}</td>
      <td>${(t.available_actions || []).map(a => `<span class="badge actions">${a}</span>`).join(' ') || '<span class="muted">—</span>'}</td>
      <td>${t.is_stale ? 'STALE' : 'live'}</td>
      <td class="muted">${fmtTime(t.updated_at)}<br>v${t.snapshot_version}</td>
    </tr>`).join('');
}

async function refresh() {
  try {
    const r = await fetch('/api/tables', { headers: H });
    if (r.ok) renderTables(await r.json());
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
      logLine((m.type || 'event') + ' ' + (m.scope || '') + ' ' + JSON.stringify(m.payload || {}));
      if (m.type === 'table') refresh();
    } catch (_) { /* keepalive */ }
  };
}

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
    out.innerHTML = res.hands.map((h, i) => `
      <div>${h.join(' ')}</div>
      <div class="eqbar"><div style="width:${res.equities[i]}%"></div></div>
      <div class="muted" style="font-size:12px">${res.equities[i]}% (${res.samples} samples)</div>
    `).join('');
  } catch (e) { out.textContent = 'request failed: ' + e; }
});

refresh();
setInterval(refresh, 5000); // slow fallback only; SSE is primary
connectSSE();
