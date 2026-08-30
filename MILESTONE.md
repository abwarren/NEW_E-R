# E&R PokerBet — MILESTONE tracker

| Milestone | Status | Evidence |
|-----------|--------|----------|
| M0 players | ✅ | tests/test_players.py 12/12; commit ac744a0 |
| M1 slice 0/1 (foundation + tracer bullet) | ✅ | tests/test_slice01.py 15/15; commit 9798b4d |
| M2 scraper (fixture-driven) | ✅ | tests/test_scraper.js 6/6 (node DOM harness) |
| M3 command queue + idempotency | ✅ | tests/test_slice01.py + e2e steps 11-15 |
| M4 equity in-process | ✅ | tests equity 3/3; e2e step 10 |
| M5 multi-table / multi-bot isolation | ✅ | tests/test_fleet_recovery.py; e2e steps 16-17 |
| M6 recovery (restart, stale, timeout) | ✅ | tests/test_fleet_recovery.py; e2e step 18 |
| M7 live PokerBet E2E (real table) | ⛔ EXTERNAL BLOCKER — valid PokerBet credentials |
| M8 PG state store | ⛔ EXTERNAL BLOCKER — postgres role provisioning (sudo) |
| M9 production deploy (systemd) | ⛔ EXTERNAL BLOCKER — sudo/systemd on this box |

All blockers are user-side actions; the code paths they gate are implemented
and covered by in-process tests (the only difference is the live host + OS).
