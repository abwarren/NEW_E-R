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

- 45 pytest: players (12), slice01 (15), fleet/recovery (6), directional equity (6),
  deployment features (3: fleet staleness via /api/tables, include_stale filter, CORS lockdown)
- 10 node tests: 6 scraper (fixture DOM matching live-verified structure) +
  4 config wiring (options→chrome.storage→w4p.js precedence, live reload)
- scripts/verify_backend.py: 21/21 (persistence, SSE events, restart recovery,
  stale 409, command state machine, directional equity, 4-player isolation)
- scripts/verify_equity_integration.py: 9/9
- scripts/verify_multidevice.py: 19/19 against the LIVE server (below)

## MULTI-DEVICE VERIFIED (live server, 2026-08-30)

`scripts/verify_multidevice.py` — two simulated independent devices
(multidev-a/multidev-a-chrome-01/T-devA-1 vs multidev-b/multidev-b-chrome-01/
T-devB-1) against the running central E&R: 19/19 PASS — attribution, shared
table-id isolation, command exclusivity (A cannot claim B's, B cannot claim
A's), cross-player ACK rejected 403, duplicate ACK idempotent, A → OFFLINE
while B stays live, A reconnect → ONLINE, both aggregated simultaneously.

Extension is now per-device configurable (options page → chrome.storage →
w4p.js, no JS editing; window.ER_* globals still override for console-paste
dev mode), remote E&R origins reachable via optional host permissions
(manifest v0.2.0), server CORS allow-list via ER_ALLOWED_ORIGINS (default
locked down), fleet dashboard shows per-player 🟢 ONLINE / 🔴 OFFLINE + browser
id + last-seen. Packaged: `dist/e-r-extension.zip`. Install guide:
`DEPLOYMENT/PLAYER_DEVICE.md`; remote server setup: docs/DEPLOYMENT.md §7.

PHYSICAL two-machine test (two real Chromes on two real devices) remains an
operator step — the server side of that test is proven above.

Not marked as failures — these are external-condition blockers, not defects.
