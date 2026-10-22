# E&R PokerBet — Milestone tracker

> Status: **PARTIAL — READY**. All code paths proven in-process. Live-table acceptance
> blocked by external credentials condition only.

---

## LIVE VERIFIED (real PokerBet, 2026-08-30)

| Item | Status | Evidence |
|------|--------|----------|
| Login | PASS | Shickey authenticated at pokerbet.co.za |
| Poker client | PASS | poker-web.pokerbet.co.za/18751019/ |
| Table discovery | PASS | Lobby → PL Omaha 4 → table 2143034 "Multan" |
| Table identity | PASS | URL /tbl/2143034 |
| Hero detection | PASS | `.player-mini-container-p.self-player.poker` seat 0 |
| Seat detection | PASS | 9 seats, 1 occupied |
| Snapshot → E&R | PASS | POST /api/snapshot 200, dashboard shows table 2143034 |
| Dashboard state | PASS | table 2143034 | shickey | PRE_FLOP | hero shickey |

## BLOCKED — external condition (ZAR 0 balance, cannot be dealt in)

| Item | Status |
|------|--------|
| Hole cards | BLOCKED |
| Board | BLOCKED |
| Pot live | BLOCKED |
| Live equity | BLOCKED |
| Live command execution | BLOCKED |
| Live ACK | BLOCKED |
| Multi-player live hand | BLOCKED |

These are not code defects. All are proven in-process. They require valid funded credentials.

---

## AUTOMATED VERIFIED

- **45 pytest**: players (12), slice01 (15), fleet/recovery (6), directional equity (6),
  deployment features (3: fleet staleness, include_stale filter, CORS lockdown)
- **10 node tests**: 6 scraper (fixture DOM) + 4 config wiring (options→chrome.storage)
- **scripts/verify_backend.py**: 21/21 (persistence, SSE, restart recovery, stale 409,
  command state machine, directional equity, 4-player isolation)
- **scripts/verify_equity_integration.py**: 9/9
- **scripts/verify_multidevice.py**: 19/19 (two simulated devices, attribution, isolation,
  command exclusivity, ONLINE/OFFLINE, simultaneous aggregation)

---

## MULTI-DEVICE VERIFIED (live server, 2026-08-30)

19/19 PASS — two independent simulated devices. Command exclusivity, cross-player 403,
duplicate ACK idempotent, A→OFFLINE while B stays live, A reconnect→ONLINE.

---

## Feature completeness

| Feature | Status | Notes |
|---------|--------|-------|
| Snapshot ingestion | ✅ | `POST /api/snapshot` |
| Composite identity partition | ✅ | (player, browser, table) key |
| Version monotonicity + stale 409 | ✅ | No silent drops |
| Hero seat stability | ✅ | Sticky across DOM flicker |
| Command queue (full state machine) | ✅ | QUEUED→DELIVERED→ACK/FAILED |
| Command exclusivity | ✅ | Cannot cross players |
| Idempotent ACK | ✅ | Duplicate = no-op |
| Lost-ACK recovery | ✅ | Re-claimable after timeout |
| Directional equity (raw + realized + disparity) | ✅ | N×(N-1) results |
| PLO mid-hand equity (flop/turn) | ✅ | MC runout, any board length |
| SSE live events | ✅ | Reconnect replay from DB |
| Unified dashboard (fleet + equity + log) | ✅ | Single page, single port |
| Fleet staleness / ONLINE/OFFLINE | ✅ | Age-based + explicit flag |
| Player accounts + OS keyring | ✅ | `scripts/er-players.py` |
| MV3 extension | ✅ | w4p.js + options page |
| Per-device config (chrome.storage) | ✅ | Live reload on save |
| Extension packaged | ✅ | `dist/e-r-extension.zip` |
| **Auto-action engine** | ✅ | `POST /api/auto_action` |
| PG migration | ✅ (config only) | Set `ER_DB_URL`, run `backend/migrations/001_postgres.sql` |
| systemd deploy | ❌ | Needs sudo — see `docs/DEPLOYMENT.md` |

---

## Next actions (operator)

1. **Credentials**: provision funded PokerBet account → run `scripts/run_e2e.py` against
   live table → update `evidence/live/`
2. **systemd**: `sudo systemctl enable/start er` (see `docs/DEPLOYMENT.md`)
3. **Auto-action UI**: add toggle buttons to dashboard per table
   (wire to `POST /api/auto_action`)
4. **GoldRush**: same BetConstruct DOM — add `poker-web.goldrush.co.za` to
   `extension/manifest.json` host_permissions

---

*Updated: 2026-10-22*
