# E&R PokerBet — Standalone remote-control + equity for PokerBet

> **Directive:** clean rebuild, PokerBet ONLY. Not pokerhud. Not multi-site.
> Single FastAPI service: scrape → state → equity → dashboard → command →
> browser → ACK.

## Status

**PARTIAL — READY**: backend, extension, 45 tests and a 16-step E2E harness all
green (in-process). Multi-device: extension config is per-device via the
options page (server URL / API key / player/browser IDs, stored in
chrome.storage); the backend aggregates any number of devices and the
dashboard shows per-player 🟢 ONLINE / 🔴 OFFLINE status. The live-table
acceptance test needs valid PokerBet credentials (EXTERNAL BLOCKER). See
`docs/REPORT-AJ.md`, `MILESTONE.md`, `DEPLOYMENT/PLAYER_DEVICE.md`.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cp .env.example .env                 # set ER_API_KEY
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8090
curl -H "X-API-Key: $ER_API_KEY" http://127.0.0.1:8090/api/health
# dashboard: http://127.0.0.1:8090/
```

Player accounts (passwords → OS keyring, never on disk):

```bash
.venv/bin/python scripts/er-players.py register --username <user> --display-name "<name>"
.venv/bin/python scripts/er-players.py list
```

Extension: chrome://extensions → Load unpacked → `extension/` → set server URL,
API key, player and browser IDs in options (per device) → open
`https://poker-web.pokerbet.co.za/18751019/`. Full per-device guide:
`DEPLOYMENT/PLAYER_DEVICE.md`.

## Layout

```
backend/          FastAPI service (config, models, schemas, state, command_queue,
                  equity, main, players/, static/ dashboard)
extension/        Chrome MV3 (manifest.json, w4p.js scraper+executor, options.html)
scripts/          er-players.py (account CLI), run_e2e.py (acceptance harness)
tests/            pytest (45) + node scraper tests (10) + dom_harness
docs/             CONTRACTS.md, DOM-MAP.md, ADR-001..005, DEPLOYMENT.md, REPORT-AJ.md
DEPLOYMENT/       PLAYER_DEVICE.md (exact per-device extension install)
dist/             packaged extension zip (e-r-extension.zip)
evidence/e2e/     E2E evidence output
```

## Gate 0 verdict (PokerBet DOM)

PokerBet runs **BetConstruct SkillGames** at `poker-web.pokerbet.co.za`
(same engine as GoldRush) — NOT EvenBet/PokerAlpha as the old plan assumed.
Full selector map: `docs/DOM-MAP.md`.
