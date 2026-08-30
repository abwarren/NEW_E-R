# E&R PokerBet — Evidence matrix (live acceptance status)

## LIVE VERIFIED (real PokerBet, authenticated account, 2026-08-30)

| Item | Status | Evidence |
|------|--------|----------|
| Login | PASS | Shickey signed into pokerbet.co.za (interactive browser) |
| Poker client | PASS | poker-web.pokerbet.co.za/18751019/ authenticated (userid present) |
| Table discovery | PASS | lobby → PL Omaha 4 → PLAY NOW → table entry |
| Table identity | PASS | `#/product/3/3/cash-cat/1/cash/198/tbl/2143034` (table 2143034 "Multan") |
| Hero detection | PASS | `.player-mini-container-p.self-player.poker` on seat 0 (shickey) |
| Seat detection | PASS | 9 seats `sg-poker-table-seat.player-1..9`, 1 occupied |
| Snapshot → E&R | PASS | POST /api/snapshot 200 (approved); dashboard lists table 2143034 |
| Dashboard state | PASS | table 2143034 | shickey | PRE_FLOP | hero shickey | v1 | SEATED |

## BLOCKED BY EXTERNAL CONDITION (account ZAR 0 balance — cannot be dealt in)

| Item | Status |
|------|--------|
| Hole cards | BLOCKED |
| Board | BLOCKED |
| Pot | BLOCKED |
| Live equity | BLOCKED |
| Live command | BLOCKED |
| Live ACK | BLOCKED |
| Multi-player live hand | BLOCKED |
| Multi-table live hand | BLOCKED |

## AUTOMATED VERIFIED (in-process, evidence in tests/ + scripts/)

- 39 pytest: players (12), slice01 (15), fleet/recovery (6), directional equity (6)
- 6 node scraper tests (fixture DOM matching live-verified structure)
- scripts/verify_backend.py: 21/21 (persistence, SSE events, restart recovery,
  stale 409, command state machine, directional equity, 4-player isolation)

Not marked as failures — these are external-condition blockers, not defects.
