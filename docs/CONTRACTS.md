# E&R PokerBet — Interface Contracts (governing)

Every layer (extension, API, service, equity engine) speaks these shapes.
Contract-first: no module invents its own structure.

## SnapshotPayload (extension → POST /api/snapshot)

```json
{
  "player_id": "p_...",            // E&R player/bot account (players DB)
  "browser_instance_id": "b_...",  // one Chrome instance per player
  "table_id": "2589954",           // PokerBet table identity (URL /tbl/<id>)
  "hand_id": "H91827",
  "snapshot_version": 4421,        // monotonic per (player,browser,table)
  "street": "FLOP",                // "" | PRE_FLOP | FLOP | TURN | RIVER | HAND_COMPLETE | SHOWDOWN
  "pot": 45.5,
  "board": ["Td","9c","3s"],
  "seats": [{"seat_no":0,"name":"Hero","stack":1000.0,"hole_cards":["As","Ks"],
             "bet":10.0,"is_hero":true,"is_dealer":false,"sitting_out":false,"active":true}],
  "hero_seat": 0,
  "available_actions": ["fold","check","call","raise"],
  "action_amounts": {"call":20.0,"raise":60.0},
  "button_state": "",
  "table_state": "SEATED",         // SEATED | LOBBY | SPECTATING
  "variant": "plo",                // plo | holdem
  "timestamp": "ISO8601"
}
```

Rules:
- `player_id` + `browser_instance_id` + `table_id` form the immutable scope.
- A browser instance auto-enrolls to its player on first snapshot; afterwards
  the binding is enforced (cross-player access → 403).
- `snapshot_version` must be monotonic per scope. Older version → HTTP 409 with
  a visible reason (never a silent drop, never a deadlock).
- Hand change at PRE_FLOP clears the old board/hole cards; the incoming pot
  (blinds) is kept.
- Hero seat is sticky: transient absence never destroys it; only an explicit
  LOBBY/SPECTATING state resets it.

## Command (operator → POST /api/commands)

```json
{
  "player_id": "p_...",
  "browser_instance_id": "b_...",
  "table_id": "2589954",
  "hand_id": "H91827",
  "action": "raise",               // fold|check|call|bet|raise|all_in|cash_out|show|run_it_twice|resume_hand|back_to_game
  "amount": 60.0
}
```

Response `CommandView`:
```json
{"command_id":"...","player_id":"...","browser_instance_id":"...","table_id":"...",
 "hand_id":"...","action":"raise","amount":60.0,"status":"QUEUED","attempts":0,
 "created_at":"ISO8601"}
```

## Command lifecycle (state machine)

```
CREATED → QUEUED → DELIVERED → EXECUTING → ACKNOWLEDGED
                          ↘ TIMEOUT → FAILED
```

- Browser claims via `GET /api/commands/pending?player_id=&browser_instance_id=`
  — exclusive per (player, browser): a command can never be claimed by another bot.
- Browser executes then `POST /api/commands/ack` with status ACKNOWLEDGED|FAILED|TIMEOUT.
- Idempotency: repeat ACK is a no-op; the extension never re-executes a
  command_id it has already executed.
- Lost-ACK safety: a DELIVERED command is re-claimable after the timeout
  window; the extension's executed-command memo prevents double execution.

## Equity (POST /api/equity)

```json
{"variant":"plo","hands":[["As","Ks","Qh","Jh"],["2c","2d","2h","2s"]],
 "board":["Kd","Qc","Ts","7h","5d"],"samples":2000}
```
→ `{"variant":"plo","hands":[...],"board":[...],"equities":[97.4,2.6],"samples":2000,"error":""}`
Invalid cards → `error` set, `equities: []` (safe failure, never a crash).

## TableView (dashboard)

Same shape as SnapshotPayload + `scope_key`, `hero_name`, `is_stale`,
`updated_at`. NEVER contains credentials.

## Players (GET /api/players)

`PlayerView` = metadata only: player_id, username, display_name, enabled, notes.
Passwords live in the OS keyring; the dashboard/API never see them.
