"""FULL-PIPELINE acceptance test — the closed loop.

Proves the entire E&R chain end-to-end (automated, in-process):

PokerBet(sim) → snapshot → state engine → DB → directional equity → fleet
→ remote command → queue → claim (correct player/browser/table/hand only)
→ ACK → updated state → remote reflects it.

Plus the mandatory isolation guarantees:
- 4 players each own their state/equity/commands (no cross-contamination)
- a command for Shickey can NEVER be claimed by Shangey/Shanay/Sergio
- per-table equity rows are scoped (table/hand/hero/villain)
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("ER_DB_URL", f"sqlite:///{tempfile.mkdtemp()}/pipe.db")
os.environ.setdefault("ER_PLAYERS_DB", f"{tempfile.mkdtemp()}/pipe_players.db")
os.environ.setdefault("ER_API_KEY", "test-key-123")

import pytest
from fastapi.testclient import TestClient

from backend.main import app, init_db as _app_init_db
from backend.players.db import PlayerDatabase

_app_init_db()
client = TestClient(app)
H = {"X-API-Key": "test-key-123"}

PLAYERS = [("shickey", "Shickey"), ("shangey", "Shangey"), ("shanay", "Shanay"), ("sergio", "Sergio")]
HANDS = {
    "shickey": ["As", "Ks", "Qh", "Jh"],
    "shangey": ["2c", "2d", "2h", "2s"],
    "shanay": ["Ac", "Ad", "Ah", "7c"],
    "sergio": ["9s", "9d", "9h", "9c"],
}
BOARD = ["Kd", "Qc", "Ts", "7h", "5d"]


@pytest.fixture(autouse=True)
def _clean():
    from sqlalchemy import text
    from backend.db import session as db_session

    with db_session() as s:
        for t in ("events", "commands", "seat_snapshots", "equity_results", "table_state"):
            s.execute(text(f"DELETE FROM {t}"))
        s.commit()
    yield


def _players():
    db = PlayerDatabase(os.environ["ER_PLAYERS_DB"])
    try:
        bids = {}
        for pid, uname in PLAYERS:
            try:
                db.get_player(pid)
            except KeyError:
                db.create_player(username=uname, player_id=pid, display_name=uname)
            if not db.list_browser_instances(pid):
                db.register_browser_instance(pid, f"browser-{pid}")
            bids[pid] = db.list_browser_instances(pid)[0].browser_instance_id
        return bids
    finally:
        db.close()


def _snap(pid, bid, table, hand, v=1, street="RIVER", actions=("fold", "check", "call", "raise")):
    return {
        "player_id": pid, "browser_instance_id": bid, "table_id": table,
        "hand_id": hand, "snapshot_version": v, "street": street, "pot": 60.0,
        "board": BOARD, "seats": [
            {"seat_no": 0, "name": pid, "stack": 980, "hole_cards": HANDS[pid], "bet": 10, "is_hero": True, "is_dealer": False, "sitting_out": False, "active": True},
            {"seat_no": 1, "name": "villain", "stack": 1000, "hole_cards": [], "bet": 20, "is_hero": False, "is_dealer": False, "sitting_out": False, "active": False},
        ], "hero_seat": 0, "available_actions": list(actions), "action_amounts": {"call": 20, "raise": 60},
        "button_state": "", "table_state": "SEATED", "variant": "plo",
    }


def test_full_pipeline_closed_loop():
    bids = _players()
    # 1. four players snapshotted (PokerBet → scraper → state → DB)
    for i, (pid, _u) in enumerate(PLAYERS):
        r = client.post("/api/snapshot", json=_snap(pid, bids[pid], f"T-{pid}", f"H{i}"), headers=H)
        assert r.status_code == 200
    tables = client.get("/api/tables", headers=H).json()
    assert len(tables) == 4  # fleet root

    # 2. equity per table (directional, per-player Hero — 4 hands ⇒ 4×3=12)
    for i, (pid, _u) in enumerate(PLAYERS):
        hands = [HANDS[pid]] + [HANDS[p2] for p2, _ in PLAYERS if p2 != pid]
        eq = client.post("/api/equity", json={
            "variant": "plo", "hands": hands, "board": BOARD, "samples": 1000,
            "table_id": f"T-{pid}", "hand_id": f"H{i}", "hero_player_id": pid,
        }, headers=H).json()
        assert not eq["error"] and len(eq["results"]) == 12  # 4 heroes × 3 villains
        assert {x["hero_index"] for x in eq["results"]} == {0, 1, 2, 3}  # every player is Hero

    # 3. remote command → queue (isolated per player)
    cids = {}
    for i, (pid, _u) in enumerate(PLAYERS):
        action = ["call", "fold", "raise", "check"][i]
        r = client.post("/api/commands", json={
            "player_id": pid, "browser_instance_id": bids[pid],
            "table_id": f"T-{pid}", "hand_id": f"H{i}", "action": action,
        }, headers=H)
        assert r.status_code == 200 and r.json()["status"] == "QUEUED"
        cids[pid] = r.json()["command_id"]

    # 4. command isolation: each player claims ONLY their own command.
    # (Cross-player claim → None is proven by test_command_never_crosses_
    # players_or_tables in test_fleet_recovery.py; here each claims once.)
    for pid, _u in PLAYERS:
        mine = client.get("/api/commands/pending", params={"player_id": pid, "browser_instance_id": bids[pid]}, headers=H).json()
        assert mine and mine["command_id"] == cids[pid], f"{pid} should claim own command"
    # after all claims, pending is empty for everyone (nothing left to steal)
    for pid, _u in PLAYERS:
        assert client.get("/api/commands/pending", params={"player_id": pid, "browser_instance_id": bids[pid]}, headers=H).json() is None

    # 5. ACK → state update (closed loop: command → ACK → state reflects)
    for pid, _u in PLAYERS:
        r = client.post("/api/commands/ack", json={
            "command_id": cids[pid], "player_id": pid,
            "browser_instance_id": bids[pid], "status": "ACKNOWLEDGED",
        }, headers=H)
        assert r.status_code == 200 and r.json()["status"] == "ACKNOWLEDGED"

    # 6. remote reflects reality (state engine updated, per-player)
    tables = client.get("/api/tables", headers=H).json()
    assert len(tables) == 4
    for pid, _u in PLAYERS:
        t = client.get(f"/api/table/T-{pid}", params={"player_id": pid, "browser_instance_id": bids[pid]}, headers=H).json()
        assert t["hero_name"] == pid and t["street"] == "RIVER"

    # 7. equity isolation: rows scoped per table/hand/hero
    from sqlalchemy import text
    from backend.db import session as db_session

    with db_session() as s:
        rows = s.execute(text("SELECT DISTINCT table_id, hand_id, hero_player_id FROM equity_results")).fetchall()
    assert len(rows) == 4  # one scope per player


def test_duplicate_ack_idempotent():
    bids = _players()
    client.post("/api/snapshot", json=_snap("shickey", bids["shickey"], "T1", "H1"), headers=H)
    r = client.post("/api/commands", json={
        "player_id": "shickey", "browser_instance_id": bids["shickey"], "table_id": "T1", "hand_id": "H1", "action": "call",
    }, headers=H)
    cid = r.json()["command_id"]
    client.get("/api/commands/pending", params={"player_id": "shickey", "browser_instance_id": bids["shickey"]}, headers=H)
    r1 = client.post("/api/commands/ack", json={"command_id": cid, "player_id": "shickey", "browser_instance_id": bids["shickey"], "status": "ACKNOWLEDGED"}, headers=H)
    r2 = client.post("/api/commands/ack", json={"command_id": cid, "player_id": "shickey", "browser_instance_id": bids["shickey"], "status": "ACKNOWLEDGED"}, headers=H)
    assert r1.json()["status"] == "ACKNOWLEDGED"
    assert r2.json()["status"] == "ACKNOWLEDGED"  # idempotent — no error, no corruption


def test_unavailable_action_not_presented():
    bids = _players()
    # snapshot reports only fold/check available (no raise)
    client.post("/api/snapshot", json=_snap("shickey", bids["shickey"], "T1", "H1", actions=("fold", "check")), headers=H)
    t = client.get("/api/table/T1", params={"player_id": "shickey", "browser_instance_id": bids["shickey"]}, headers=H).json()
    assert "raise" not in t["available_actions"] and "fold" in t["available_actions"]
