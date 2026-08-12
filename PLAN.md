# NEW_E-R — Greenfield Rebuild Plan

> **Directive:** Rebuild the E&R poker remote-control + equity platform from scratch in a new
> repository. The legacy codebase (github.com/abwarren/E-R) is declared "built poorly, not
> architected correctly, many bugs" — this plan replaces it with a clean, modular, efficient
> architecture built with **vertical slicing** and **tracer bullets**, orchestrated by
> **parallel AI agents**.
>
> **Status:** ⏳ PLAN ONLY — no code until shared understanding is reached.
> **Governance:** This repo follows a simplified EOP (Engineering Operating Procedure) —
> PLAN FIRST → APPROVAL → SNAPSHOT → IMPLEMENT → TEST → SNAPSHOT → COMMIT → PUSH → REVIEW.
> No code is written before a plan is approved.

---

## 1. Why Rebuild (Legacy Failure Analysis)

The legacy `E-R` repo (106 commits, 16,492 LOC) was the source of constant bug-chasing. Measured facts:

| # | Legacy Problem | Evidence | Root Cause |
|---|---------------|----------|-----------|
| 1 | Monolithic backend | `backend/app.py` = 3,963 lines | No module separation |
| 2 | Monolithic scraper | `source/w4p.js` = 2,190 lines | DOM logic + state + commands entangled |
| 3 | Duplicate state (8 copies) | `_tables`, `state_snapshot.json` ×2, `buffer.py`, extension `_preAction`, UI `preActionState`, engine textarea, event bus | No single source of truth |
| 4 | Multi-bot state collision | `_tables` indexed by `table_id` alone; structural fields overwritten unconditionally | No `(table_id, hand_id)` partition |
| 5 | Epoch deadlock | 409 `stale_snapshot` permanent rejection (2026-06-20) | Server bumping epoch in-place before resync |
| 6 | Snapshot silent drops | `_lastSendTime` pre-set → every snapshot dropped after tick 5 | Timing bug in scraper |
| 7 | Selection oscillation / flicker | Remote UI flickers between two game states | `_select_best_table()` heuristic (28.6% authority accuracy) |
| 8 | Inter-service HTTP hop | Remote → Express :4000 → Flask :1080 → Engine :5002 | 3 processes, 2 network hops, PNA/CORS pain |
| 9 | Seat instability | Hero fallback removed → all seats expire in 5s | Stale cleanup keyed on `is_hero` |
| 10 | Hardcoded IPs | `192.168.0.106` in w4p.js broke PNA | No config layer |

**Design principles for the rebuild:**

1. **Single service** — one process, one port, no HTTP hops. Equity engine imported in-process.
2. **One source of truth per state type** — PostgreSQL-backed state, no JSON file persistence.
3. **Modular** — one module per concern, 100–400 lines each, never a monolith.
4. **Event-driven** — SSE push replaces polling (eliminates ~93% of HTTP traffic).
5. **Config-driven** — no hardcoded IPs, keys, or ports; everything env-based.
6. **Typed interfaces** — dataclasses/TypedDict everywhere, no dict soup.
7. **Testable by design** — every module has a unit test; every slice has an integration test.
8. **Agent-orchestrated** — parallel subagents build independent slices against shared contracts.

---

## 2. Target Architecture

```
┌────────────────────────────────────────────────────────────┐
│                 NEW_E-R Single Service                       │
│  ┌────────────────────────────────────────────────────────┐ │
│  │                    FastAPI App (:8000)                  │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │ │
│  │  │ API Layer    │  │ SSE Layer    │  │ Static UI    │  │ │
│  │  │ (REST routes)│  │ (EventSource)│  │ (dashboard)  │  │ │
│  │  └──────┬───────┘  └──────┬───────┘  └──────────────┘  │ │
│  │         └────────┬────────┘                             │ │
│  │  ┌───────────────▼──────────────────────────────────┐   │ │
│  │  │                Service Layer                      │   │ │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐          │   │ │
│  │  │  │ Table    │ │ Command  │ │ Auto-    │          │   │ │
│  │  │  │ Manager  │ │ Queue    │ │ Actions  │          │   │ │
│  │  │  └──────────┘ └──────────┘ └──────────┘          │   │ │
│  │  └───────────────┬──────────────────────────────────┘   │ │
│  │  ┌───────────────▼──────────────────────────────────┐   │ │
│  │  │              Persistence Layer                    │   │ │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────────────┐  │   │ │
│  │  │  │ SQLAlchemy│ │ Event    │ │ State Store      │  │   │ │
│  │  │  │ (PG)     │ │ Log      │ │ (versioned)      │  │   │ │
│  │  │  └──────────┘ └──────────┘ └──────────────────┘  │   │ │
│  │  └───────────────┬──────────────────────────────────┘   │ │
│  │  ┌───────────────▼──────────────────────────────────┐   │ │
│  │  │               Equity Engine (in-process)          │   │ │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐          │   │ │
│  │  │  │ PLO      │ │ eval7    │ │ Result   │          │   │ │
│  │  │  │ Calculator│ │ (Omaha) │ │ Parser   │          │   │ │
│  │  │  └──────────┘ └──────────┘ └──────────┘          │   │ │
│  │  └──────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  External:                                                  │
│    PostgreSQL (er_hands DB @ host:5432, new schema)         │
│    W4P v2 scraper (injected JS in browser)                  │
│    Operator dashboard (static UI, SSE live)                 │
└─────────────────────────────────────────────────────────────┘
```

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Framework | **FastAPI** (async) | Native async/await, SSE, WebSocket, Pydantic validation, OpenAPI docs. Flask 3.1 is sync; async is the right model for SSE push + concurrent snapshot ingestion |
| State | **PostgreSQL** (existing `er_hands` DB) | Already running on host:5432; JSONB for runtime state, relational for history. No JSON files |
| UI | **Static HTML+JS** served by the app (no Express/Node) | Eliminates the entire Express proxy layer + PNA headache. One port, one process |
| Extension comms | **Direct to :8000** via CORS headers + API key | No bridge needed in v2. Chrome PNA solved via `--disable-web-security` flag in launch config |
| Equity | **eval7 imported in-process** | No subprocess, no HTTP hop. Same library, direct calls |
| Scraper | **w4p-v2.js** (~500 lines) | Modular selectors per platform (EvenBet, BetConstruct), config-driven |

### Efficiency Gains (vs legacy)

| Metric | Legacy | NEW_E-R | Gain |
|--------|--------|---------|------|
| Backend LOC | 3,963-line monolith | ~1,500 lines across modules | -62% |
| Scraper LOC | 2,190 lines | ~500 lines | -77% |
| Processes | 3 (Express, Flask, Engine) | 1 | -66% |
| Ports | 3 (4000, 1080, 5002) | 1 (8000) | -66% |
| HTTP hops per snapshot | 2 (browser→Express→Flask→Engine) | 1 (browser→app) | -50% |
| State copies | 8 | 1 (PG) | -87% |
| Polling traffic | 4 req/s per UI | SSE push | -93% |

---

## 3. Repository Layout (NEW_E-R)

```
NEW_E-R/
├── backend/                    # Python service (FastAPI)
│   ├── app.py                  # App factory + wiring (~60 lines)
│   ├── config.py               # Env-based config, pydantic-settings (~40 lines)
│   ├── models/                 # SQLAlchemy ORM models + Pydantic schemas
│   │   ├── table.py            # TableState, TableView
│   │   ├── seat.py             # SeatData
│   │   ├── command.py          # Command
│   │   └── event.py            # Event (SSE log)
│   ├── routes/                 # API blueprints
│   │   ├── health.py           # GET /api/health
│   │   ├── snapshot.py         # POST /api/snapshot
│   │   ├── tables.py           # GET /api/tables, /api/table/{id}
│   │   ├── commands.py         # POST/GET /api/commands/*
│   │   ├── equity.py           # POST /api/equity, GET /api/engine/stream
│   │   ├── events.py           # GET /api/events (SSE)
│   │   └── auth.py             # API key auth
│   ├── services/               # Business logic
│   │   ├── table_manager.py    # Snapshot ingestion, authority, seat stability
│   │   ├── command_queue.py    # PG-backed command queue
│   │   ├── auto_actions.py     # C/F, C/C, KH decision engine
│   │   ├── event_bus.py        # In-process event bus → SSE fanout
│   │   └── state_store.py      # PG CRUD, versioned writes
│   ├── engine/                 # Equity engine (in-process)
│   │   ├── calculator.py       # PLO equity wrapper
│   │   ├── eval7_bridge.py     # eval7 import + normalization
│   │   └── result_parser.py    # Parse eval7 output → structured results
│   ├── scrapers/               # Selector profiles (config-driven)
│   │   ├── evenbet.py          # EvenBet/PokerAlpha DOM selectors
│   │   ├── betconstruct.py     # GoldRush/BetConstruct DOM selectors
│   │   └── registry.py         # Selector registry (validated at startup)
│   ├── static/                 # Operator dashboard (served by FastAPI)
│   │   ├── index.html          # Dashboard shell
│   │   └── app.js              # SSE client + table grid + equity panel
│   └── requirements.txt        # fastapi, uvicorn, sqlalchemy, asyncpg, pydantic-settings, eval7
├── extension/                  # Chrome MV3 extension (w4p-v2)
│   ├── manifest.json           # MV3, host_permissions for game domains
│   ├── w4p.js                  # DOM scraper + command executor (~500 lines)
│   ├── background.js           # Service worker: fetch relay + API key
│   └── selectors/              # Per-platform selector JSON profiles
│       ├── evenbet.json
│       └── betconstruct.json
├── migrations/                 # Alembic migrations
│   └── versions/001_init.py    # Initial schema
├── tests/
│   ├── unit/                   # Per-module unit tests
│   ├── integration/            # Slice integration tests
│   └── e2e/                    # Full-pipeline tracer bullets
├── scripts/
│   ├── launch-browsers.py      # Browser fleet launcher (Chromium/Brave)
│   └── deploy.sh               # Docker build + up + health check
├── docker-compose.yml          # Single service + Postgres (host or container)
├── Dockerfile                  # Python 3.12-slim + uvicorn
├── .env.example                # All env vars documented (no secrets committed)
├── ARCHITECTURE.md             # Living architecture doc (updated per slice)
├── MILESTONE.md                # Milestone tracker (EOP)
└── README.md                   # Quick start
```

**What is NOT carried over from legacy:**
- Express proxy (`server.js`, `server-container.js`) — eliminated (FastAPI serves static + API)
- Flask → Engine HTTP hop — eliminated (in-process eval7)
- `state_snapshot.json` persistence — replaced by PG
- `buffer.py` epoch machinery — replaced by clean snapshot versioning
- `action_router.py` CDP WebSocket injection — replaced by extension-side command polling
- `bot_deployment.py` / `windows_routes.py` — replaced by browser fleet launcher script
- `table_scraper.py` (old/not primary path) — replaced by w4p-v2.js
- `auth_models.py` Flask-Login — replaced by API-key auth (single header)
- `audit_logs.py` — replaced by event log table
- All investigation/, logs/, pokerbet-trace/ artifacts — not copied (history stays in E-R repo)
- `backend-reference/`, `nginx-reference/`, `service-reference/`, `env-reference/` — not copied (docs live in ARCHITECTURE.md)

---

## 4. Vertical Slices (Build Sequence)

Each slice is a **complete vertical slice through ALL layers** — API → service → persistence → scraper/UI. Each slice ends with a working, demonstrable, tested artifact. **Slices are strictly sequential** — no slice starts before the previous is approved.

### Slice 0: Repo skeleton + CI + contracts (foundation)

**Goal:** Empty repo becomes a buildable, testable project with shared interface contracts.

- [ ] `config.py` — pydantic-settings, all env vars with defaults
- [ ] `app.py` factory + health route + CORS + API-key auth middleware
- [ ] Pydantic schemas for all DTOs (SnapshotPayload, SeatData, TableView, Command, Event)
- [ ] SQLAlchemy models + Alembic migration 001
- [ ] Dockerfile + docker-compose.yml (single service)
- [ ] pytest + ruff + mypy config, CI workflow (GitHub Actions)
- [ ] **Interface Contract document** (`docs/CONTRACTS.md`) — the shared contract for all agents
- [ ] **Evidence:** `pytest` green on health route + schema validation; `docker compose up` serves `/api/health`

### Slice 1: Tracer Bullet — Lobby → Snapshot → Store → Serve

**Core question:** "Can I prove this architecture works end-to-end?"

- [ ] POST /api/snapshot { seats, table_id } → 200 + stored in PG
- [ ] GET /api/tables → list including just-posted table
- [ ] GET /api/table/{id} → full table state
- [ ] GET / (dashboard) → shows table state visibly
- [ ] Mutate input → new POST → state updates
- [ ] Edge case: empty seats handled gracefully
- [ ] w4p-v2.js skeleton: polls DOM, posts snapshot
- [ ] **Tracer bullet definition:** one snapshot → one PG row → one UI render, proven with a live test

### Slice 2: Table Interaction — Sit → Scrape → Queue → Click

- [ ] W4P v2 detects hero seat (EvenBet `.self-player`)
- [ ] POST /api/snapshot includes hole cards, board, pot, available_actions
- [ ] POST /api/commands/queue { action, amount? } → queued in PG
- [ ] GET /api/commands/pending → next command for bot
- [ ] W4P v2 polls pending, executes click, sends ACK
- [ ] Edge case: no button found → retry + timeout

### Slice 3: Equity Engine In-Process + SSE

- [ ] POST /api/equity { hands, board } → equity % for each hand (eval7 direct)
- [ ] Results streamed via SSE (no polling)
- [ ] Dashboard shows equity grid
- [ ] Edge case: invalid cards → clear error

### Slice 4: Command Automation + Multi-Table

- [ ] Auto fold/check/call when no bet/raise needed
- [ ] KH (Knallhard) mode — always raise/bet
- [ ] Execute on hero's turn only
- [ ] Configurable per-table rules (PG-backed)
- [ ] Multi-table: `(table_id, bot_id)` partition, no state collision
- [ ] Edge case: disconnected table → pause, reconnect → resume

### Slice 5: GoldRush (BetConstruct) Multi-Platform

- [ ] W4P v2 detects both EvenBet and BetConstruct DOM
- [ ] Selector profile switches based on hostname
- [ ] All existing GoldRush tables work
- [ ] Single API, single state store, single UI

---

## 5. Tracer Bullets

Every slice ships with a tracer bullet — a thin, end-to-end validation that fires through every layer.

### TB-001: Snapshot Pipeline (Slice 1)

```
curl -X POST :8000/api/snapshot -H 'X-API-Key: ...' -d '{seats, table_id}'
  → 200, PG row written
curl :8000/api/tables           → table visible
curl :8000/api/table/pb_test    → full state
open :8000/                     → dashboard renders table
```

**Acceptance:** single command chain proves API → service → PG → UI in under 30 seconds.

### TB-002: Command Roundtrip (Slice 2)

```
POST /api/commands/queue {action:'fold'}
GET  /api/commands/pending     → fold
extension executes click → POST /api/commands/ack
GET  /api/commands/pending     → empty
```

### TB-003: Equity Streaming (Slice 3)

```
POST /api/equity {hands:[...], board:[...]}
SSE stream: progress → final percentages
UI grid renders results
```

### TB-004: Auto-Action (Slice 4)

```
snapshot with hero + available_actions:[call]
auto-rule C/C → command queued automatically
extension executes → ACK
```

### TB-005: Multi-Platform (Slice 5)

```
same snapshot shape, two different hostnames
selector registry picks profile → identical output shape
```

Each tracer bullet has a **test harness** (`tests/e2e/test_tb00X.py`) with explicit pass/fail assertions and evidence capture (log + JSON snapshot). Evidence is committed to `evidence/` per slice.

---

## 6. Agent Orchestration

The rebuild is executed by **parallel AI agents** (subagents), coordinated by the orchestrator (this Hermes session). The pattern follows `launch-subagent` + `parallel-subagent-contracts`:

### Orchestrator Responsibilities
- Write and maintain the **Interface Contract** (`docs/CONTRACTS.md`) — exact class/method/signature names every agent must use
- Decompose slices into **self-contained agent tasks** with zero file overlap
- Dispatch agents (Fable 5 Max / GPT 5.6 Sol Max Fast only per launch-subagent)
- Review/verify every agent output before accepting it (contract verification script)
- Run tracer bullets + integration tests after each slice
- Commit + push verified work only

### Agent Task Graph (per slice)

```
Slice N (orchestrator)
├── Agent A: backend module X   (independent file set)
├── Agent B: backend module Y   (independent file set, parallel with A)
├── Agent C: frontend/extension  (independent file set, parallel)
└── Orchestrator: integration + tests + tracer bullet + commit
```

### Interface Contract (docs/CONTRACTS.md) — defined BEFORE any agent runs

```python
# Example contract excerpt (full doc in docs/CONTRACTS.md)
# Persistence layer
class StateStore:
    async def save_snapshot(self, table_id: str, bot_id: str, payload: SnapshotPayload) -> None: ...
    async def get_table(self, table_id: str, bot_id: str) -> TableView | None: ...
    async def list_tables(self) -> list[TableView]: ...

# Service layer
class TableManager:
    async def process_snapshot(self, payload: SnapshotPayload) -> TableView: ...
    async def get_table_view(self, table_id: str, bot_id: str) -> TableView: ...

# Event bus
class EventBus:
    async def publish(self, event: Event) -> None: ...
    def subscribe(self, handler: Callable[[Event], Awaitable[None]]) -> None: ...

# Equity engine
class EquityCalculator:
    async def calculate(self, hands: list[list[str]], board: list[str]) -> EquityResult: ...
```

**Rules:**
- Contract lives in the repo, reviewed by orchestrator, frozen per slice
- Every agent gets the contract **in its task context** (subagents start blind)
- Agents never touch the same file — file ownership table per slice
- After each batch: orchestrator runs `scripts/verify_contracts.py` — imports by expected names, fails fast
- Agents are leaf workers (no nested delegation) — orchestrator owns integration

### Agent Model Rules (launch-subagent)
- Subagents: **Fable 5 Max** or **GPT 5.6 Sol Max Fast** ONLY
- Never Composer/Sonnet for subagents
- Destructive commands run by orchestrator in main loop (subagents blocked by approval gate)
- Batch results are truncated — orchestrator reads full reports from `/home/wa/.hermes/cache/delegation/` before synthesizing

---

## 7. Database Schema (PostgreSQL, `er_hands` DB)

Existing schema from `000-init-schema.sql` (already written in legacy repo) is adapted. Core tables:

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `platforms` | EvenBet, BetConstruct | id, name, domain |
| `game_types` / `game_categories` | Game classification | id, code, name |
| `navigation_items` | Site nav tree (data-driven) | id, parent_id, platform_id |
| `poker_tables` | Table registry | id, table_id, platform_id, name, stakes |
| `table_sessions` | Runtime sessions | id, table_id, bot_id, started_at, ended_at |
| `seats` | Seat state history | id, session_id, seat_no, player_name, stack |
| `commands` | Command queue (PG-backed) | id, table_id, bot_id, action, amount, status |
| `hand_history` | Hand records | id, table_id, hand_id, street, board, pot |
| `equity_results` | Equity calc results | id, hand_id, hands, board, equity_pcts |
| `events` | Event log (SSE replay) | id, type, payload, created_at |
| `automation_rules` | Per-table auto-action config | id, table_id, rule_type, enabled |
| `runtime_state` | JSONB versioned runtime state | table_id, bot_id, payload, version, updated_at |

**Key design:** `runtime_state` is the SINGLE source of truth for live table state (versioned JSONB,
write-through cache, no duplicate state copies). Historical data (hands, equity, events) is relational.

---

## 8. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Agent contract mismatch (class names) | Medium | High | `docs/CONTRACTS.md` + `scripts/verify_contracts.py` after every batch |
| EvenBet selectors change | Medium | High | Selector registry with startup validation gate |
| Chrome PNA blocks extension→API | Low (v2 direct :8000) | Medium | `--disable-web-security` launch flag; CORS headers; same-machine loopback |
| PG connection fails | Low | Medium | Connection pool with retry + graceful degradation (legacy db_logger pattern) |
| Equity engine errors | Medium | Medium | Isolated in try/except; graceful degradation |
| W4P v2 breaks existing tables | Medium | High | Legacy `E-R` repo untouched during rebuild; parallel deployment possible |
| Agent files collide | Medium | High | Strict file ownership table per slice; orchestrator enforces |

---

## 9. Rollback Strategy

- **Per slice:** each slice is tagged (`v2.0.0-slice-N`). Any instability → `git revert` to previous tag.
- **Parallel deployment:** legacy E-R keeps running during the rebuild (it's deployed as Docker containers on the VM). NEW_E-R deploys side-by-side on port 8000. No downtime.
- **Data safety:** new schema in same `er_hands` DB but with distinct table names (`new_` prefix if needed) — no destructive migration of legacy tables.

---

## 10. Milestones (EOP MILESTONE.md)

| Milestone | Objective | Deliverable | Evidence |
|-----------|-----------|-------------|----------|
| M0 | Skeleton + contracts | Buildable repo, CI green | `pytest` pass, `/api/health` 200 |
| M1 (Slice 1) | Tracer bullet pipeline | Snapshot → PG → UI | TB-001 harness green |
| M2 (Slice 2) | Table interaction | Queue → execute → ACK | TB-002 harness green |
| M3 (Slice 3) | Equity in-process + SSE | Equity grid live | TB-003 harness green |
| M4 (Slice 4) | Automation + multi-table | Auto C/F, C/C, KH | TB-004 harness green |
| M5 (Slice 5) | GoldRush multi-platform | Both platforms live | TB-005 harness green |

---

## 11. Status

- [x] Legacy analysis (this document)
- [x] Target architecture
- [x] Vertical slice map
- [x] Tracer bullet definitions
- [x] Agent orchestration design
- [x] DB schema plan
- [ ] **APPROVAL** ← awaiting shared understanding
- [ ] Slice 0 (skeleton + contracts)
- [ ] Slice 1 (tracer bullet)
- [ ] Slice 2 (table interaction)
- [ ] Slice 3 (equity + SSE)
- [ ] Slice 4 (automation + multi-table)
- [ ] Slice 5 (GoldRush multi-platform)

---

*This document is the single source of truth for the NEW_E-R rebuild. It is updated only at milestone boundaries (EOP Phase 6) and versioned in git.*
