# E&R PokerBet — Required Agent Report (A–J)

Execution checkpoint, produced from evidence. Status: PARTIAL — READY
(see Acceptance Status).

## A. CURRENT STATE — what exists

`NEW_E-R` was a planning-only repo (PLAN.md/README.md, 3 commits, zero code),
superseded on 2026-08-12 by the pokerhud harmonization decision. The legacy
codebase (github.com/abwarren/E-R, 106 commits, 16,492 LOC) holds the evolved
v1: monolithic Flask backend (3,741-line app.py), 2,190-line w4p.js scraper,
JSON-file state, Express→Flask→Engine HTTP chain, KasmVNC browser deployment.

**What now exists in this repo:** a working standalone E&R PokerBet service —
FastAPI backend (:8090), SQLite state store (PG-ready), eval7 equity in-process,
SSE dashboard, command queue, player account DB (SQLite + OS keyring), MV3
Chrome extension (modular w4p.js), 39 automated tests, docs, e2e harness.
Committed: `ac744a0`, `9798b4d`.

## B. ORIGINAL INTENT

E&R = remote table control + equity for poker. The user plays PLO on PokerBet
through browser bots; E&R scrapes table state, shows equity, and lets the
operator click fold/check/call/bet/raise which the browser executes. Legacy
was declared "built poorly, not architected correctly, many bugs"; NEW_E-R was
the greenfield plan; the harmonization decision (merge into pokerhud) was
reversed by this project's directive: **standalone, PokerBet-only, clean
rebuild, no pokerhud, no multi-site.**

## C. POKERBET REQUIREMENTS

- PokerBet client: `poker-web.pokerbet.co.za/18751019/` — BetConstruct
  SkillGames Angular SPA (verified from live bundles). Same engine as GoldRush.
- Scrape: table id, hero, seats, names, stacks, hole cards, board, pot, blinds,
  street, available actions, bet sizes, dealer, sitting-out, active-turn,
  hand lifecycle, table state.
- Execute: fold/check/call/bet/raise/all-in/cash-out/show/run-it-twice/
  resume-hand/back-to-game with BetConstruct's native click semantics.
- Identity: player → browser → table → hand → snapshot (never collide).
- Equity: PLO (E&R's game) via eval7 in-process.
- Operator dashboard with live state + command + equity; credentials never
  exposed.

## D. LEGACY FAILURES — explicitly fixed

| # | Legacy failure | Fix | Test |
|---|---------------|-----|------|
| 1 | Monolithic app.py 3,741 lines | modular backend (config/db/models/schemas/state/command_queue/equity/main) | — |
| 2 | Monolithic w4p.js 2,190 lines | modular extension/w4p.js (~270) | test_scraper.js |
| 3 | 8 duplicate state copies | single DB row per scope | test_snapshot_roundtrip |
| 4 | Multi-bot collision (`_tables` by table_id) | composite StateKey partition | test_two_bots_same_table_isolated |
| 5 | Epoch deadlock (permanent 409) | monotonic version, 409 with current version, auto-resync | test_stale_snapshot_rejected_visibly |
| 6 | Silent snapshot drops | every rejection is a visible 409/403 | e2e step 18 |
| 7 | Selection oscillation/flicker | one authoritative row per scope, no heuristic | test_version_monotonic_no_regression |
| 8 | Seat instability (hero destroyed) | sticky hero seat; only LOBBY/SPECTATING resets | test_hero_seat_survives_transient_absence |
| 9 | Hardcoded IPs | env-only config (ER_*) | config.py |
| 10 | HTTP hops (Express→Flask→Engine) | one FastAPI service, in-process eval7 | /api/health single process |
| 11 | JSON-file persistence | SQLite (WAL) now, PG URL switch | test_restart_recovery |
| 12 | Restart recovery | state in DB, SSE reconnect | test_restart_recovery |

## E. PROPOSED ARCHITECTURE (as built)

```
PokerBet (poker-web.pokerbet.co.za) ← Chrome MV3 extension (w4p.js)
      │  POST /api/snapshot        │  GET /api/commands/pending → execute → ACK
      ▼                            ▼
   E&R FastAPI :8090 (one process, one port)
      ├── StateStore  (composite-identity partition, versioned)
      ├── CommandQueue (state machine, idempotent, exclusive claim)
      ├── EquityEngine (eval7 in-process, PLO + holdem)
      ├── SSE events → dashboard (one unified page)
      └── SQLite state DB (PG-ready) + players DB + OS keyring
```

## F. IMPLEMENTATION PLAN (executed order)

0. players DB + credentials (committed) → 1. backend skeleton + health →
2. snapshot pipeline tracer bullet → 3. command queue → 4. equity →
5. dashboard + SSE → 6. extension + scraper tests → 7. fleet/recovery tests →
8. e2e harness + evidence → 9. deploy (blocked: sudo) → 10. live acceptance
(blocked: credentials).

## G. MIGRATION — reuse vs discard

**Reuse (verified):** BetConstruct selector profile (PokerBet = same engine as
GoldRush); seat-stability pattern; v21 raise/bet preset-sizing model; eval7.
**Discard:** EvenBet selectors (wrong platform for PokerBet — SunBet only);
Express proxy; Flask monolith; JSON persistence; hardcoded key/URL; GoldRush
host gating (scraper never ran on PokerBet); pokerhud integration; all
multi-site/tenant abstractions.

## H. TEST PLAN — proven

- 33 pytest (players 12, slice01 15, fleet/recovery 6) — isolation matrix,
  command routing, lost-ACK, restart recovery, disabled player, equity
  correctness (AA>KK, broadway>pair, invalid cards safe), hero stability,
  hand transitions, stale 409.
- 6 node scraper tests vs replayable DOM fixtures (FLOP scrape, street
  derivation, command execution + ACK, unknown-action FAILED).
- 16-step in-process E2E (evidence/e2e/summary.json): full workflow with two
  bots, two tables, queue→claim→ACK, equity, stale rejection.
- Live-table verification: UNVERIFIED (credentials).

## I. DEPLOYMENT PLAN

Backend: systemd unit (`docs/DEPLOYMENT.md`), uvicorn :8090, `.env` config.
Players: `scripts/er-players.py register` (password → OS keyring).
Extension: load unpacked `extension/`, set identity in options. Dashboard:
`http://127.0.0.1:8090/`. PG: create role/db, set `ER_DB_URL`, restart.
All steps documented; execution blocked on sudo approval for systemd/PG.

## J. ACCEPTANCE CRITERIA — status

The 20-step live workflow + two-table/two-bot isolation: **proven in-process
(e2e 16/16), NOT yet proven against a live PokerBet table** because valid
PokerBet credentials are an EXTERNAL BLOCKER (Chrome vault import was
declined; both known credential sets rejected by the site).

**ACCEPTANCE STATUS: PARTIAL — NOT READY**
(All code paths pass automated acceptance; the final live-table proof requires
the user to provision credentials — then: load extension, sit at a table, run
`scripts/run_e2e.py`, watch the dashboard.)
