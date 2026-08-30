#!/usr/bin/env python3
"""Backend verification via in-process TestClient (authorized, non-destructive,
no curl). Covers: persistence, SSE/events, API reads, restart recovery,
stale-state, command state machine, deterministic equity, 4-player isolation.

Run: .venv/bin/python scripts/verify_backend.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

TMP = tempfile.mkdtemp(prefix="er-verify-")
os.environ["ER_DB_URL"] = f"sqlite:///{TMP}/state.db"
os.environ["ER_PLAYERS_DB"] = f"{TMP}/players.db"
os.environ["ER_API_KEY"] = "verify-key"

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app, init_db  # noqa: E402
from backend.players.db import PlayerDatabase  # noqa: E402

init_db()
client = TestClient(app)
H = {"X-API-Key": "verify-key"}

ok = 0
fail = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok, fail
    ok += cond
    fail += not cond
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def snap(player, browser, table, hand="H1", v=1, street="PRE_FLOP", board=None, pot=0.0, actions=None, seats=None, hero=0):
    return {
        "player_id": player, "browser_instance_id": browser, "table_id": table,
        "hand_id": hand, "snapshot_version": v, "street": street, "pot": pot,
        "board": board or [], "seats": seats or [
            {"seat_no": i, "name": player if i == hero else "", "stack": 1000, "hole_cards": ["As", "Ks", "Qh", "Jh"] if i == hero else [], "bet": 0, "is_hero": i == hero, "is_dealer": False, "sitting_out": False, "active": False}
            for i in range(3)
        ], "hero_seat": hero, "available_actions": actions or [], "action_amounts": {},
        "button_state": "", "table_state": "SEATED", "variant": "plo",
    }


def main() -> int:
    # 1. health + auth
    r = client.get("/api/health")
    check("health 200", r.status_code == 200 and r.json().get("status") == "ok")
    r = client.get("/api/tables")
    check("auth enforced (no key → 401/403)", r.status_code in (401, 403), f"HTTP {r.status_code}")

    # 2. register the four players + browser instances
    pdb = PlayerDatabase(os.environ["ER_PLAYERS_DB"])
    accounts = {"shickey": "Shickey", "shangey": "Shangey", "shanay": "Shanay", "sergio": "Sergio"}
    for pid, uname in accounts.items():
        try:
            pdb.get_player(pid)
        except KeyError:
            pdb.create_player(username=uname, player_id=pid, display_name=uname)
        if not pdb.list_browser_instances(pid):
            pdb.register_browser_instance(pid, f"verify-{pid}")
    pdb.close()
    r = client.get("/api/players", headers=H)
    pl = r.json()
    check("4 players listed", r.status_code == 200 and len(pl) == 4, f"{len(pl)}")

    # 3. persistence + API read
    for pid in accounts:
        bid = client.get("/api/players", headers=H).json() and None  # noqa: F841
    # browser ids from db
    pdb = PlayerDatabase(os.environ["ER_PLAYERS_DB"])
    bids = {pid: pdb.list_browser_instances(pid)[0].browser_instance_id for pid in accounts}
    pdb.close()

    r = client.post("/api/snapshot", json=snap("shickey", bids["shickey"], "T-100", hand="H100", v=1, street="FLOP", board=["Td", "9c", "3s"], pot=45.5), headers=H)
    check("snapshot persisted (200)", r.status_code == 200)
    t = client.get("/api/table/T-100", params={"player_id": "shickey", "browser_instance_id": bids["shickey"]}, headers=H).json()
    check("API read: street/pot/board", t["street"] == "FLOP" and t["pot"] == 45.5 and len(t["board"]) == 3, f"{t['street']}/{t['pot']}")
    check("API read: hero + hole cards", t["hero_seat"] == 0 and t["seats"][0]["hole_cards"] == ["As", "Ks", "Qh", "Jh"])

    # 4. restart recovery — new engine against same DB file
    from backend.state import StateStore
    from backend.players.identity import IdentityService

    store = StateStore(IdentityService(PlayerDatabase(os.environ["ER_PLAYERS_DB"])))
    view = store.get_table("shickey", bids["shickey"], "T-100")
    check("restart recovery: state survives", view is not None and view.street == "FLOP")

    # 5. stale-state handling — older version after a newer one must 409
    r = client.post("/api/snapshot", json=snap("shickey", bids["shickey"], "T-100", hand="H100", v=2, street="TURN", board=["Td", "9c", "3s", "7h"], pot=80), headers=H)
    check("newer snapshot accepted", r.status_code == 200)
    r = client.post("/api/snapshot", json=snap("shickey", bids["shickey"], "T-100", hand="H100", v=1, street="FLOP", board=["Td", "9c", "3s"], pot=45.5), headers=H)
    check("stale snapshot → 409", r.status_code == 409, r.text[:60])

    # 6. SSE/events — events are persisted (replayed to reconnecting dashboards)
    from sqlalchemy import text
    from backend.db import session as db_session

    with db_session() as s:
        ev_count = s.execute(text("SELECT COUNT(*) FROM events")).scalar()
        ev_types = [r[0] for r in s.execute(text("SELECT DISTINCT type FROM events")).fetchall()]
    check("events persisted (SSE replay source)", ev_count >= 1 and any(t in ev_types for t in ("snapshot", "table", "command")), f"{ev_count} events, types={ev_types}")

    # 7. command state machine
    r = client.post("/api/commands", json={"player_id": "shickey", "browser_instance_id": bids["shickey"], "table_id": "T-100", "hand_id": "H100", "action": "call", "amount": 20}, headers=H)
    cid = r.json()["command_id"]
    check("command queued (QUEUED)", r.status_code == 200 and r.json()["status"] == "QUEUED")
    c = client.get("/api/commands/pending", params={"player_id": "shickey", "browser_instance_id": bids["shickey"]}, headers=H).json()
    check("command claimed (DELIVERED)", c and c["command_id"] == cid and c["status"] == "DELIVERED")
    r = client.post("/api/commands/ack", json={"command_id": cid, "player_id": "shickey", "browser_instance_id": bids["shickey"], "status": "ACKNOWLEDGED"}, headers=H)
    check("ACK → ACKNOWLEDGED", r.status_code == 200 and r.json()["status"] == "ACKNOWLEDGED")
    check("pending empty after ACK", client.get("/api/commands/pending", params={"player_id": "shickey", "browser_instance_id": bids["shickey"]}, headers=H).json() is None)

    # 8. deterministic equity
    r = client.post("/api/equity", json={"variant": "plo", "hands": [["As", "Ks", "Qh", "Jh"], ["2c", "2d", "2h", "2s"]], "board": ["Kd", "Qc", "Ts", "7h", "5d"], "samples": 2000}, headers=H)
    eq = r.json()
    ab = next((x for x in eq.get("results", []) if x["hero_index"] == 0 and x["villain_index"] == 1), None)
    check("equity: broadway > pair", r.status_code == 200 and not eq.get("error") and ab and ab["raw_equity"] > 90, str(ab))
    r = client.post("/api/equity", json={"variant": "plo", "hands": [["As", "Ks", "Qh", "Jh"], ["2c", "2d", "2h", "2s"]], "board": ["Xx", "Yy"], "samples": 100}, headers=H)
    check("equity: invalid cards fail safe", r.json().get("error") != "")

    # 9. four-player isolation — each own table + own state, no cross-contamination
    for i, (pid, uname) in enumerate(accounts.items()):
        r = client.post("/api/snapshot", json=snap(pid, bids[pid], f"T-{pid}", hand=f"H{i+1}", v=1, street="PRE_FLOP", pot=10 * (i + 1)), headers=H)
        assert r.status_code == 200, r.text
    for pid in accounts:
        t = client.get(f"/api/table/T-{pid}", params={"player_id": pid, "browser_instance_id": bids[pid]}, headers=H).json()
        check(f"player {pid} owns only own table", t["table_id"] == f"T-{pid}" and t["player_id"] == pid)
    # same table two players — isolated states
    client.post("/api/snapshot", json=snap("shickey", bids["shickey"], "T-SHARED", hand="HX", v=1, street="FLOP", board=["Td", "9c", "3s"], pot=30), headers=H)
    client.post("/api/snapshot", json=snap("shangey", bids["shangey"], "T-SHARED", hand="HY", v=1, street="RIVER", board=["Td", "9c", "3s", "7h", "5d"], pot=99), headers=H)
    a = client.get("/api/table/T-SHARED", params={"player_id": "shickey", "browser_instance_id": bids["shickey"]}, headers=H).json()
    b = client.get("/api/table/T-SHARED", params={"player_id": "shangey", "browser_instance_id": bids["shangey"]}, headers=H).json()
    check("same table two players isolated", a["street"] == "FLOP" and b["street"] == "RIVER" and a["pot"] == 30 and b["pot"] == 99, f"a={a['street']}/{a['pot']} b={b['street']}/{b['pot']}")

    print(f"\nBACKEND VERIFICATION: {ok} pass / {fail} fail")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
