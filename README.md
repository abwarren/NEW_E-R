# NEW_E-R — Greenfield E&R Poker Platform Rebuild

Greenfield rebuild of the E&R poker remote-control + equity platform. Replaces the
poorly-engineered legacy codebase at [github.com/abwarren/E-R](https://github.com/abwarren/E-R)
with a clean, modular, single-service architecture built with vertical slicing and tracer bullets,
orchestrated by parallel AI agents.

**Status: ⏳ PLANNING — no code until the plan (PLAN.md) is approved.**

## Quick Links

- **Plan:** [PLAN.md](PLAN.md) — full greenfield architecture, vertical slice map, tracer bullets, agent orchestration
- **Legacy repo:** [github.com/abwarren/E-R](https://github.com/abwarren/E-R) (106 commits, 16,492 LOC, being replaced)
- **Old rebuild plan (superseded):** `.hermes/plans/E&R-REBUILD-PLAN.md` in the legacy repo

## What's Wrong With Legacy (why rebuild)

| Problem | Evidence |
|---------|----------|
| Monolithic backend | `backend/app.py` = 3,963 lines |
| Monolithic scraper | `source/w4p.js` = 2,190 lines |
| Duplicate state (8 copies) | in-memory dicts + JSON files + extension + UI |
| Multi-bot state collision | `_tables` indexed by `table_id` alone |
| Epoch deadlock | 409 `stale_snapshot` permanent rejection |
| Snapshot silent drops | `_lastSendTime` timing bug |
| Selection oscillation/flicker | 28.6% authority accuracy heuristic |
| 3 processes, 2 HTTP hops | Express :4000 → Flask :1080 → Engine :5002 |
| Hardcoded IPs | `192.168.0.106` broke Chrome PNA |

## Target Architecture (one paragraph)

Single FastAPI service on one port (:8000): REST API + SSE push + one unified dashboard page
(remote control grid + equity calculator together — not two pages), PostgreSQL-backed state in a
fresh `new_er` database (no JSON files), eval7 equity engine imported in-process (no HTTP hop),
modular w4p-v2.js scraper (~500 lines) with per-platform selector profiles (EvenBet + BetConstruct).
Built in 5 vertical slices, each ending with a tested, demonstrable tracer bullet. Parallel AI
subagents implement independent modules against a frozen interface contract (`docs/CONTRACTS.md`).

## Build Sequence (vertical slices)

| Slice | What It Proves | Tracer Bullet |
|-------|---------------|---------------|
| 0 | Repo skeleton + contracts + CI | `/api/health` 200, pytest green |
| 1 | Lobby → Snapshot → Store → Serve | TB-001: one snapshot → PG row → UI render |
| 2 | Sit → Scrape → Queue → Click | TB-002: queue → execute → ACK |
| 3 | Equity in-process + SSE | TB-003: cards → equity % streamed to UI |
| 4 | Auto C/F, C/C, KH + multi-table | TB-004: auto-rule → queued → executed |
| 5 | GoldRush (BetConstruct) multi-platform | TB-005: both platforms, one API |

Full details: [PLAN.md](PLAN.md)

## Repo Layout (target)

```
backend/          FastAPI service (app factory, routes, services, engine, scrapers)
extension/        Chrome MV3 extension (w4p-v2.js, background.js, selector profiles)
migrations/       Alembic migrations
tests/            unit/ + integration/ + e2e/ (tracer bullet harnesses)
scripts/          browser launcher, deploy.sh, verify_contracts.py
docs/             CONTRACTS.md (agent interface contracts), ARCHITECTURE.md
```

## Getting Started (once approved)

```bash
git clone git@github.com:abwarren/NEW_E-R.git
cd NEW_E-R
cp .env.example .env        # add real keys
docker compose up -d        # single service + Postgres
curl localhost:8000/api/health
```
