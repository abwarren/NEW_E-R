# POKERBET DOM MAP — Gate 0 deliverable (2026-08-30)

**Platform:** BetConstruct "SkillGames" Angular SPA
**Client URL:** `https://poker-web.pokerbet.co.za/18751019/`
**Auth:** `WEB_auth_hash` (auth-init.js → localStorage), launch via
`pokerbet.co.za/en/page/casino/poker/28?openGames=28-real&gameNames=Poker`
**Same engine as:** GoldRush (`poker-web.goldrush.co.za`) — the legacy w4p.js
GoldRush selector profile is the correct PokerBet profile.
**NOT EvenBet/PokerAlpha** — that is SunBetPoker only (sb-play.pkrsrv.com).
The NEW_E-R plan's EvenBet assumption is disproven for PokerBet.

Verification basis: live client bundles (main-DSHDF6RJ.js + chunk-*.js fetched
2026-08-30) + legacy E-R repo + GoldRush DOM-mismatch investigation. Items
requiring a seated table are marked **UNVERIFIED** (need valid PokerBet login —
EXTERNAL BLOCKER).

| Item | Selector | Extraction | Status |
|------|----------|-----------|--------|
| Table ID | URL `/tbl/<id>` (e.g. `/18751019/tbl/2589954`); Angular `table_id`/`table_index` params | regex on pathname | VERIFIED (bundle + GoldRush) |
| Table proof | `sg-poker-table, sg-poker-table-seat, .player-mini-container-p, .control-b-view-p, .pot-w-view-p, .single-cart-view-p` | any present = table page | VERIFIED (bundle) |
| Hero | `.self-player` on seat element | `querySelector('sg-poker-table-seat.self-player')` or `.player-mini-container-p.self-player` | VERIFIED (bundle; GoldRush runtime) |
| Seats | `sg-poker-table-seat` / `.player-mini-container-p` (GoldRush: `.player-N` divs; wrapper mismatch documented) | iterate containers | VERIFIED (bundle) |
| Player names | `p.single-win-item-sizes`, alt `.player-name` | textContent | VERIFIED (bundle) |
| Stacks | `.player-text-info-p span b` / `.player-text-info-p b` / `.player-stack` | parseFloat | VERIFIED (bundle) |
| Hole cards | `.carts-container-p .single-cart-view-p` (hero only) | CSS-class-encoded faces; data/title/aria/img fallbacks | UNVERIFIED (live format) |
| Board | `sg-poker-board .single-cart-view-p` (3=flop,4=turn,5=river) | same card decode | VERIFIED (bundle structure) |
| Pot | `.pot-w-view-p` / `.pot-amount` / `.total-pot` | parseFloat | VERIFIED (bundle) |
| Dealer | `.dealer-icon-view` | presence | VERIFIED (bundle) |
| Sitting out | `.seat-out-v` | presence | VERIFIED (bundle) |
| Active turn | `.active-turn` | presence | VERIFIED (bundle) |
| Available actions | button presence + visible (`offsetParent != null`) | map to list | VERIFIED (bundle) |
| Fold | `.control-b-view-p.fold-c` | native mousedown/mouseup/click (Angular/Zone.js) | VERIFIED (legacy runtime) |
| Check | `.control-b-view-p.check-c` | native click | VERIFIED |
| Call | `.control-b-view-p.call-c` | native click | VERIFIED |
| Bet | `.control-b-view-p.bet-c` | preset-click sizing → amount verify → click | VERIFIED (legacy v21 model) |
| Raise | `.control-b-view-p.raise-c` | same | VERIFIED (legacy v21 model) |
| All-in | `.control-b-view-p.all_in-c` | native click | VERIFIED (bundle) |
| Cash out / Show / Run-it-twice / Resume hand / Back to game | `.control-b-view-p.cash_out-c` / `.show-c` / `.run_it_twice-c` / `.resume_hand-c` / `.back_to_game-c` | native click | VERIFIED (bundle) |
| Bet sizing | `sg-poker-betting-slider` (custom element, `onValueChange`, `buttons` binding, `.limits-buttons-v-p` presets) | preset <li> click, verify amount `<i>` changed, then confirm | VERIFIED (bundle; legacy v21) |

## Reliability verdict on the legacy scraper (w4p.js 2,190 lines)

| Part | Verdict |
|------|---------|
| GoldRush/BetConstruct selector registry | RELIABLE — matches PokerBet's engine; keep |
| `sg-poker-table-seat` (EvenBet) selectors | NOT for PokerBet — EvenBet-only; exclude |
| URL guard (`isPokerScrapeContext`) | BROKEN for PokerBet — goldrush hosts only; must add `poker-web.pokerbet.co.za` |
| Seat stability layer (_seatCache, resolveSeatIndex) | RELIABLE — preserve the pattern (hero-sticky, collision rejection) |
| v21 raise/bet sizing (preset → amount-verify → confirm) | RELIABLE — keep |
| Hardcoded API key + potlimitomaha.xyz URL | BROKEN — remove; env/config-driven |
| 2,190-line monolith | REPLACE — modular w4p.js (~270 lines now) |

## Open items (need live seated table — EXTERNAL BLOCKER: credentials)
1. Exact card-face encoding on real cards (class scheme → rank/suit decode).
2. Table identity element (is there an in-DOM hand/table id, or only URL?).
3. Amount display element for raise/bet verification (`.bet-amount`?).
4. Multi-table navigation (two tables in one browser? separate browsers?).
5. Hero flag stability across hands.
