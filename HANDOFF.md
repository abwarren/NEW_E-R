# E&R PokerBet — HANDOFF

**Always-current. Update this file every time you change something meaningful.**
Last updated: 2026-10-22

---

## What this project is

Remote table-control + directional equity calculator for PokerBet (BetConstruct SkillGames,
`poker-web.pokerbet.co.za`). One FastAPI service, one MV3 Chrome extension.

- Operator sits at the dashboard and clicks fold/check/call/raise — the command routes to the
  correct browser and the extension executes the native DOM click.
- Live equity (raw vs realized vs disparity) shown per hand via eval7 in-process.
- Multi-device: any number of Chrome instances, each identified by `player_id` +
  `browser_instance_id`. No state collision between players or tables.

This is a **standalone** rebuild of the legacy E-R repo (106 commits, monolith, many bugs).
It does NOT integrate with pokerhud or any other site. PokerBet only.

---

## Current status (as of HANDOFF date)

| Area | Status |
|------|--------|
| Backend (FastAPI :8090) | ✅ Complete |
| SQLite state store | ✅ Complete (PG-ready via ER_DB_URL) |
| Command queue + ACK cycle | ✅ Complete |
| Directional equity (raw + realized + disparity) | ✅ Complete |
| SSE live dashboard | ✅ Complete |
| Chrome MV3 extension (scraper + executor) | ✅ Complete |
| Player accounts + OS keyring | ✅ Complete |
| Auto-actions engine (threshold fold/check/call/raise) | ✅ Added |
| PLO mid-hand equity (flop/turn) | ✅ Fixed — MC runout |
| Multi-device verified (19/19) | ✅ Proven in-process |
| **Live PokerBet table (real credentials)** | ❌ **EXTERNAL BLOCKER** |
| systemd deploy | ❌ Needs sudo (operator step) |

**The only unresolved blocker is live PokerBet credentials.** All code paths pass
in-process acceptance (45 pytest + 16-step E2E + 10 node scraper tests).

---

## Repo layout

```
backend/
  main.py            FastAPI app — all routes, SSE, wiring
  config.py          Env-based config (ER_* vars, pydantic-settings)
  models.py          SQLAlchemy ORM: TableState, Command, Event, EquityResult
  schemas.py         Pydantic contracts — the single shared interface
  state.py           StateStore: snapshot ingestion, hero stability, versioning
  command_queue.py   CommandQueue: QUEUED→DELIVERED→ACK state machine
  equity.py          Directional equity: raw + realized + disparity (eval7)
  auto_actions.py    Threshold auto-action engine (fold/check/call/raise)
  db.py              SQLite engine + session factory
  players/           Player account DB + OS keyring + identity resolution
  static/
    index.html       Unified dashboard (fleet control + equity panel + log)
    app.js           SSE client, command dispatch, equity UI

extension/
  manifest.json      MV3, host_permissions for poker-web.pokerbet.co.za
  w4p.js             DOM scraper + command executor (~270 lines)
  options.html       Per-device config: API base, API key, player ID, browser ID

tests/
  test_players.py         Player account lifecycle (12 tests)
  test_slice01.py         Core pipeline: snapshot → state → command → equity (15 tests)
  test_fleet_recovery.py  Multi-device isolation + restart recovery (6 tests)
  test_equity_directional.py  Directional equity contract (6 tests)
  test_deployment_features.py Fleet staleness, CORS lockdown (3 tests)
  test_scraper.js         DOM scraper against fixture HTML (6 tests)
  test_config_storage.js  Extension options page wiring (4 tests)

scripts/
  er-players.py           Player account CLI (register/list/delete)
  run_e2e.py              16-step in-process E2E harness
  verify_backend.py       21-assertion backend verification
  verify_equity_integration.py  9-assertion equity verification
  verify_multidevice.py   19-assertion multi-device verification

docs/
  CONTRACTS.md            API contract (governing) — read before changing schemas
  DOM-MAP.md              PokerBet DOM selector map (live-verified 2026-08-30)
  DEPLOYMENT.md           Server-side deployment (systemd, PG, nginx)
  REPORT-AJ.md            Full A–J agent report (project history + acceptance status)
  adr/ADR-001-005.md      Architecture decisions
DEPLOYMENT/
  PLAYER_DEVICE.md        Per-device extension install guide (step-by-step)
```

---

## How to run (dev)

```bash
cd NEW_E-R
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cp .env.example .env         # set ER_API_KEY (any string works for dev)
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8090 --reload
# dashboard: http://127.0.0.1:8090/
# health:    curl -H "X-API-Key: $ER_API_KEY" http://127.0.0.1:8090/api/health
```

Register a player account (required before the extension sends snapshots):
```bash
.venv/bin/python scripts/er-players.py register --username shickey --display-name "Shickey"
```

Run all tests:
```bash
.venv/bin/pytest -v
```

Run the E2E harness (in-process, no real PokerBet needed):
```bash
.venv/bin/python scripts/run_e2e.py
```

---

## How to install the extension

See `DEPLOYMENT/PLAYER_DEVICE.md`. Short version:
1. `chrome://extensions` → Developer mode → Load unpacked → select `extension/`
2. Extension options: set API base, API key, player ID, browser ID
3. Open `https://poker-web.pokerbet.co.za/18751019/`
4. Dashboard should show `🟢 ONLINE` for the player within 2 seconds

---

## Environment variables (.env)

```
ER_API_KEY=your-secret-key           # required; all API calls must include X-API-Key header
ER_DB_URL=                           # leave blank for SQLite; set postgresql+psycopg2://... for PG
ER_PLAYERS_DB=                       # path to players SQLite file (default: players.db)
ER_STALE_SNAPSHOT_SECONDS=30        # seconds before a table is marked STALE / OFFLINE
ER_ALLOWED_ORIGINS=                  # comma-separated CORS origins; blank = locked down
```

---

## Key design decisions (read before changing anything)

**1. Composite identity is mandatory.**
Every snapshot is keyed by `(player_id, browser_instance_id, table_id)`. Never index by
`table_id` alone — that is the legacy multi-bot collision bug. The schema enforces a unique
constraint on the triple.

**2. Snapshot version is monotonic.**
A snapshot with a lower version than the stored version returns HTTP 409 (visible, never
silent). The extension auto-recovers by bumping its seq counter past the server's version.

**3. Hero seat is sticky.**
Transient DOM flicker never destroys the hero seat. Only an explicit `LOBBY` or `SPECTATING`
table_state resets it. See `state.py:_resolve_hero()`.

**4. Equity is directional, not aggregate.**
`N` players → `N × (N−1)` results. Each result has `hero_index`, `villain_index`,
`raw_equity`, `realized_equity`, `disparity`. There is no single-number "table equity".
See `docs/CONTRACTS.md` for the full contract.

**5. PLO equity uses Monte Carlo runout.**
PLO equity is computed at any street (pre-flop through river) by running out the remaining
cards. The board only needs to be valid (0, 3, 4, or 5 cards). Each PLO hand evaluation
uses the best combination over all 2-of-4 × 3-of-5 combos.

**6. Auto-actions are conservative.**
`backend/auto_actions.py` implements threshold-based decisions: equity < 20% → fold,
20–35% → check/fold, 35–50% → call, 50–70% → raise, >70% → pot raise.
It is **opt-in per table** via `POST /api/auto_action`. It never acts unless
`needs_action` is explicitly set in the snapshot (guarded against phantom fires).

**7. Commands are idempotent.**
The extension tracks executed `command_id`s in memory and never re-executes. The server
also guards: a duplicate ACK is a no-op; a DELIVERED command is re-claimable after timeout
only (lost-ACK safety).

---

## What still needs to happen (next session)

| Priority | Task | Where |
|----------|------|--------|
| HIGH | Provision live PokerBet credentials → run `scripts/run_e2e.py` against a real table | External |
| HIGH | `sudo systemctl enable/start er` on the server — see `docs/DEPLOYMENT.md` | Server |
| MEDIUM | Wire `POST /api/auto_action` into the dashboard UI (toggle button per table) | `backend/static/app.js` |
| LOW | Postgres migration — set `ER_DB_URL` and run `backend/migrations/001_postgres.sql` | Server |
| LOW | Multi-platform: BetConstruct on GoldRush shares the same DOM — extension already works, just change the hostname whitelist in `manifest.json` | `extension/manifest.json` |

---

## Known limitations / gotchas

- **Hole cards on non-hero seats are never visible** — PokerBet hides opponent hole cards until
  showdown. Realized equity uses a random villain range (this is correct; it matches what
  the hero actually knows).

- **Hand ID is derived, not scraped** — PokerBet does not expose a `data-hand-id` attribute on
  the live client. The scraper derives it as `H<unix-timestamp-seconds>`. This means hand
  boundaries are approximate (±1s). The stale-hand guard in command execution uses this ID,
  so false rejections are possible at exact hand boundaries. If PokerBet ever exposes the ID,
  update `w4p.js:scrapeTable()`.

- **Bet sizing uses preset buttons only** — raise/bet commands click a preset that matches the
  requested amount to the nearest cent. If no matching preset exists, the action fires without
  sizing (browser keeps last amount). A full slider drag implementation is possible but not
  built.

- **SQLite WAL is fine for one server** — if you add a second server instance sharing the DB,
  switch to Postgres.

---

## Repo history / lineage

- `abwarren/E-R` — original monolith (106 commits, 16 492 LOC). Legacy only; do not continue it.
- `abwarren/RemoteControl` — throwaway prototype. Ignore.
- `abwarren/NEW_E-R` (this repo) — clean rebuild. **This is the active codebase.**
- `abwarren/new_er` — over-architected refactor of NEW_E-R; introduced multi-site scope that was
  explicitly cut. Abandoned. The `ThresholdEngine` from `new_er` was ported into `backend/auto_actions.py`.

---

*Update this file every time you add a feature, fix a bug, change a contract, or hit a blocker.*
