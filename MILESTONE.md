# E&R PokerBet — MILESTONE tracker

| Milestone | Status | Evidence |
|-----------|--------|----------|
| M0 players | ✅ | tests/test_players.py 12/12; commit ac744a0 |
| M1 slice 0/1 (foundation + tracer bullet) | ✅ | tests/test_slice01.py; commit 9798b4d |
| M2 scraper (fixture-driven) | ✅ | tests/test_scraper.js 6/6 (node DOM harness) |
| M3 command queue + idempotency | ✅ | tests/test_slice01.py + e2e steps 11-15 |
| M4 equity in-process | ✅ | tests/test_equity_directional.py 6/6 |
| M5 multi-table / multi-bot isolation | ✅ | tests/test_fleet_recovery.py; e2e steps 16-17 |
| M6 recovery (restart, stale, timeout) | ✅ | tests/test_fleet_recovery.py; e2e step 18 |
| M7 directional equity model (raw/realized/disparity) | ✅ | test_equity_directional.py; verify_backend.py 21/21 |
| M8 live PokerBet login/table/DOM/snapshot | ✅ | evidence/live/ (login, table 2143034, hero, seats, snapshot→E&R) |
| M9 live dealt-hand (hole/board/pot/actions/equity/command/ACK) | ⛔ EXTERNAL BLOCKER — account ZAR 0 balance |
| M10 PG state store | 🟡 code ready (migrations/001_postgres.sql); provision needs postgres role (user) |
| M11 production deploy (systemd) | ⛔ EXTERNAL BLOCKER — sudo/systemd on this box |

All blockers are user-side actions; the code paths they gate are implemented
and covered by in-process tests (the only difference is the live host + OS).
