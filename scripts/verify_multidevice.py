"""Multi-device validation against the LIVE central E&R server.

Simulates two independent player devices (A and B) — distinct player, browser
and table identities — exercising the multi-device directive's acceptance
matrix: attribution, isolation, command exclusivity, disconnect → OFFLINE,
reconnect, simultaneous aggregation.

Usage:
    .venv/bin/python scripts/verify_multidevice.py [BASE] [API_KEY]

Defaults: BASE=http://127.0.0.1:8090  API_KEY=er-dev-local
Requires:  the E&R server running with a SHORT ER_STALE_SNAPSHOT_SECONDS
(suggest 4) so the disconnect test completes quickly; the server DB path via
ER_PLAYERS_DB if not the default data/players.db.

Exit code 0 = all PASS. Test rows are removed from the server DB afterwards.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

# allow running as scripts/verify_multidevice.py from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ER_API_BASE", "http://127.0.0.1:8090")
API_KEY = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("ER_API_KEY", "er-dev-local")
STALE_WAIT = float(os.environ.get("ER_STALE_WAIT_SECONDS", "8"))
H = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}" + (f"  — {detail}" if detail else ""))
    else:
        failed += 1
        print(f"  FAIL  {name}" + (f"  — {detail}" if detail else ""))


def req(method, path, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers=H, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = raw.decode(errors="replace")
        return e.code, parsed


def snap(player, browser, table, hand, version, street, board):
    return {
        "player_id": player, "browser_instance_id": browser, "table_id": table,
        "hand_id": hand, "snapshot_version": version, "street": street, "pot": 25.0,
        "board": board,
        "seats": [
            {"seat_no": 0, "name": player, "stack": 1000.0, "hole_cards": ["As", "Ks", "Qh", "Jh"],
             "bet": 5.0, "is_hero": True, "is_dealer": True, "sitting_out": False, "active": True},
            {"seat_no": 1, "name": "villain", "stack": 990.0, "hole_cards": [], "bet": 5.0,
             "is_hero": False, "is_dealer": False, "sitting_out": False, "active": False},
        ],
        "hero_seat": 0, "available_actions": ["fold", "check", "call", "raise"],
        "action_amounts": {}, "button_state": "", "table_state": "SEATED",
        "variant": "plo", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


A = ("multidev-a", "multidev-a-chrome-01", "T-devA-1", "H-A1")
B = ("multidev-b", "multidev-b-chrome-01", "T-devB-1", "H-B1")
pa, ba, ta, ha = A
pb, bb, tb, hb = B

# ── register the two players (browsers auto-enroll on first snapshot) ──────
from backend.players.db import PlayerDatabase  # noqa: E402

_pdb = PlayerDatabase(os.environ.get("ER_PLAYERS_DB", "data/players.db"))
try:
    for pid, name in (("multidev-a", "devA"), ("multidev-b", "devB")):
        try:
            _pdb.get_player(pid)
        except KeyError:
            _pdb.create_player(username=name, player_id=pid, display_name=name)
finally:
    _pdb.close()

print(f"central E&R: {BASE}")
print("device A:", " / ".join(A))
print("device B:", " / ".join(B))
print()

# 1. server health
s, _ = req("GET", "/api/health")
check("server health", s == 200)

# 2. both devices send snapshots
s, _ = req("POST", "/api/snapshot", snap(pa, ba, ta, ha, 1, "FLOP", ["Kd", "Qc", "Ts"]))
check("device A snapshot accepted", s == 200, f"status {s}")
s, _ = req("POST", "/api/snapshot", snap(pb, bb, tb, hb, 1, "TURN", ["Kd", "Qc", "Ts", "9h"]))
check("device B snapshot accepted", s == 200, f"status {s}")

# 3. attribution: A's state is A's, B's state is B's
s, rows = req("GET", "/api/tables")
check("tables list ok", s == 200)
by_key = {(r["player_id"], r["table_id"]): r for r in rows}
a_row, b_row = by_key.get((pa, ta)), by_key.get((pb, tb))
check("A attributed to A", bool(a_row) and a_row["street"] == "FLOP" and a_row["browser_instance_id"] == ba)
check("B attributed to B", bool(b_row) and b_row["street"] == "TURN" and b_row["browser_instance_id"] == bb)

# 4. same table_id on both devices stays isolated (composite key, not table id)
req("POST", "/api/snapshot", snap(pa, ba, "T-shared", "H-X", 1, "PRE_FLOP", []))
req("POST", "/api/snapshot", snap(pb, bb, "T-shared", "H-Y", 1, "PRE_FLOP", []))
s, rows = req("GET", "/api/tables")
shared = [r for r in rows if r["table_id"] == "T-shared"]
check("shared table id isolated per player",
      len(shared) == 2 and {r["player_id"] for r in shared} == {pa, pb})

# 5. command for A: B cannot claim it, A can
s, c = req("POST", "/api/commands",
           {"player_id": pa, "browser_instance_id": ba, "table_id": ta, "hand_id": ha, "action": "fold"})
cid_a = c["command_id"]
check("command for A queued", s == 200 and bool(cid_a))
s, claim_b = req("GET", f"/api/commands/pending?player_id={pb}&browser_instance_id={bb}")
check("B cannot claim A's command", claim_b is None)
s, claim_a = req("GET", f"/api/commands/pending?player_id={pa}&browser_instance_id={ba}")
check("A claims its own command",
      bool(claim_a) and claim_a["command_id"] == cid_a and claim_a["action"] == "fold")

# 6. command for B: A cannot claim it, B can
s, c = req("POST", "/api/commands",
           {"player_id": pb, "browser_instance_id": bb, "table_id": tb, "hand_id": hb, "action": "call"})
cid_b = c["command_id"]
s, claim_a2 = req("GET", f"/api/commands/pending?player_id={pa}&browser_instance_id={ba}")
check("A cannot claim B's command", claim_a2 is None)
s, claim_b2 = req("GET", f"/api/commands/pending?player_id={pb}&browser_instance_id={bb}")
check("B claims its own command", bool(claim_b2) and claim_b2["command_id"] == cid_b)

# 7. ACK ownership + idempotency
s, _ = req("POST", "/api/commands/ack",
           {"command_id": cid_a, "player_id": pb, "browser_instance_id": bb, "status": "ACKNOWLEDGED"})
check("cross-player ACK rejected (403)", s == 403, f"status {s}")
s, _ = req("POST", "/api/commands/ack",
           {"command_id": cid_a, "player_id": pa, "browser_instance_id": ba, "status": "ACKNOWLEDGED"})
check("A ACK accepted", s == 200)
s, r = req("POST", "/api/commands/ack",
           {"command_id": cid_a, "player_id": pa, "browser_instance_id": ba, "status": "ACKNOWLEDGED"})
check("duplicate ACK idempotent", s == 200 and r["status"] == "ACKNOWLEDGED")

# 8. disconnect A → OFFLINE; B (still heartbeating) stays live
print(f"  … device B keeps sending for {STALE_WAIT:.0f}s while A is silent")
deadline = time.time() + STALE_WAIT
b_version = 2
while time.time() < deadline:
    req("POST", "/api/snapshot", snap(pb, bb, tb, hb, b_version, "TURN", ["Kd", "Qc", "Ts", "9h"]))
    b_version += 1
    time.sleep(1)
s, rows = req("GET", "/api/tables")
by_key = {(r["player_id"], r["table_id"]): r for r in rows}
check("A OFFLINE after disconnect", by_key[(pa, ta)]["is_stale"] is True)
check("B still live", by_key[(pb, tb)]["is_stale"] is False)

# 9. reconnect A → ONLINE, version advanced
req("POST", "/api/snapshot", snap(pa, ba, ta, ha, 2, "FLOP", ["Kd", "Qc", "Ts"]))
s, rows = req("GET", "/api/tables")
by_key = {(r["player_id"], r["table_id"]): r for r in rows}
check("A reconnects → ONLINE",
      by_key[(pa, ta)]["is_stale"] is False and by_key[(pa, ta)]["snapshot_version"] == 2)

# 10. both devices aggregated simultaneously
s, rows = req("GET", "/api/tables")
ids = {(r["player_id"], r["browser_instance_id"]) for r in rows}
check("both devices aggregated in one dashboard view", (pa, ba) in ids and (pb, bb) in ids)

# ── cleanup: remove validation rows from the server DB ─────────────────────
from backend.db import session as db_session  # noqa: E402
from sqlalchemy import text  # noqa: E402

with db_session() as s_:
    s_.execute(text("DELETE FROM table_state WHERE player_id IN ('multidev-a','multidev-b')"))
    s_.execute(text("DELETE FROM commands WHERE player_id IN ('multidev-a','multidev-b')"))
    s_.execute(text("DELETE FROM seat_snapshots WHERE scope LIKE 'player=multidev-%'"))
    s_.execute(text("DELETE FROM events WHERE scope LIKE 'player=multidev-%'"))
    s_.commit()

print(f"\nMULTI-DEVICE VALIDATION: {passed} pass / {failed} fail")
sys.exit(1 if failed else 0)
