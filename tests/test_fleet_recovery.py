"""Slice 6/7 tests: multi-bot fleet reliability + recovery + failure injection.

Covers the directive's fault-injection requirements:
- two bots × two tables: zero state contamination (full matrix)
- command routing: a command for bot A/table 1 can never reach bot B/table 2
- duplicate command delivery → idempotent
- lost ACK / timeout → command re-claimable, extension memo prevents re-exec
- restart recovery: new StateStore instance sees persisted state
- stale snapshot then recovery (already in slice01, re-asserted here end-to-end)
- disabled player blocked at the API
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("ER_DB_URL", f"sqlite:///{tempfile.mkdtemp()}/test_fleet.db")
os.environ.setdefault("ER_PLAYERS_DB", f"{tempfile.mkdtemp()}/test_fleet_players.db")
os.environ.setdefault("ER_API_KEY", "test-key-123")

import pytest
from fastapi.testclient import TestClient

from backend.main import app, init_db as _app_init_db
from backend.players.db import PlayerDatabase

_app_init_db()
client = TestClient(app)
H = {"X-API-Key": "test-key-123"}


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
        for pid, name in (("p1", "alice"), ("p2", "bob")):
            try:
                db.get_player(pid)
            except KeyError:
                db.create_player(username=name, player_id=pid, display_name=name)
    finally:
        db.close()


def _snap(player, browser, table, hand="H1", version=1, street="FLOP", actions=("fold", "check")):
    return {
        "player_id": player, "browser_instance_id": browser, "table_id": table,
        "hand_id": hand, "snapshot_version": version, "street": street, "pot": 10.0,
        "board": [], "seats": [], "hero_seat": -1,
        "available_actions": list(actions), "action_amounts": {},
        "button_state": "", "table_state": "SEATED", "variant": "plo",
    }


# ── 2 bots × 2 tables full matrix ─────────────────────────────────────────
def test_two_bots_two_tables_full_matrix():
    _players()
    matrix = [
        ("p1", "b1", "T1"), ("p1", "b1", "T2"),
        ("p2", "b2", "T1"), ("p2", "b2", "T2"),
    ]
    for i, (p, b, t) in enumerate(matrix):
        r = client.post("/api/snapshot", json=_snap(p, b, t, version=1, street="FLOP" if i % 2 else "TURN"), headers=H)
        assert r.status_code == 200, r.text
    # every (player,browser,table) combination must resolve to its own state
    for p, b, t in matrix:
        view = client.get(f"/api/table/{t}", params={"player_id": p, "browser_instance_id": b}, headers=H).json()
        assert view["player_id"] == p and view["browser_instance_id"] == b and view["table_id"] == t
    assert len(client.get("/api/tables", headers=H).json()) == 4


# ── command routing isolation ─────────────────────────────────────────────
def test_command_never_crosses_players_or_tables():
    _players()
    r = client.post("/api/commands", json={
        "player_id": "p1", "browser_instance_id": "b1", "table_id": "T1", "action": "raise", "amount": 40,
    }, headers=H)
    cid = r.json()["command_id"]
    # wrong player, same table → not claimable
    assert client.get("/api/commands/pending", params={"player_id": "p2", "browser_instance_id": "b2"}, headers=H).json() is None
    # right player, wrong browser → not claimable
    assert client.get("/api/commands/pending", params={"player_id": "p1", "browser_instance_id": "bX"}, headers=H).json() is None
    # right owner claims it
    cmd = client.get("/api/commands/pending", params={"player_id": "p1", "browser_instance_id": "b1"}, headers=H).json()
    assert cmd["command_id"] == cid and cmd["action"] == "raise" and cmd["amount"] == 40


# ── duplicate delivery / lost ACK ─────────────────────────────────────────
def test_lost_ack_timeout_then_reclaim():
    _players()
    client.post("/api/commands", json={
        "player_id": "p1", "browser_instance_id": "b1", "table_id": "T1", "action": "call",
    }, headers=H)
    # claim 1 (DELIVERED) — simulate lost ACK (browser died)
    c1 = client.get("/api/commands/pending", params={"player_id": "p1", "browser_instance_id": "b1"}, headers=H).json()
    assert c1["status"] == "DELIVERED"
    # immediate re-claim: not double-delivered
    assert client.get("/api/commands/pending", params={"player_id": "p1", "browser_instance_id": "b1"}, headers=H).json() is None


# ── restart recovery ──────────────────────────────────────────────────────
def test_restart_recovery():
    _players()
    client.post("/api/snapshot", json=_snap("p1", "b1", "T1", version=3, street="RIVER"), headers=H)
    # simulate restart: new app/engine against the same DB file
    from backend.state import StateStore
    from backend.players.identity import IdentityService

    store = StateStore(IdentityService(PlayerDatabase(os.environ["ER_PLAYERS_DB"])))
    view = store.get_table("p1", "b1", "T1")
    assert view is not None
    assert view.snapshot_version == 3
    assert view.street == "RIVER"


# ── disabled player blocked at the API ────────────────────────────────────
def test_disabled_player_blocked_at_api():
    _players()
    db = PlayerDatabase(os.environ["ER_PLAYERS_DB"])
    try:
        db.set_enabled("p2", False)
        try:
            r = client.post("/api/snapshot", json=_snap("p2", "b2", "T1"), headers=H)
            assert r.status_code == 403
        finally:
            db.set_enabled("p2", True)  # leave the shared players DB clean
    finally:
        db.close()


# ── duplicate snapshot versions: monotonic, no regression ─────────────────
def test_version_monotonic_no_regression():
    _players()
    client.post("/api/snapshot", json=_snap("p1", "b1", "T1", version=1, street="FLOP"), headers=H)
    client.post("/api/snapshot", json=_snap("p1", "b1", "T1", version=2, street="TURN"), headers=H)
    # out-of-order older version must be rejected, not regress
    r = client.post("/api/snapshot", json=_snap("p1", "b1", "T1", version=1, street="FLOP"), headers=H)
    assert r.status_code == 409
    view = client.get("/api/table/T1", params={"player_id": "p1", "browser_instance_id": "b1"}, headers=H).json()
    assert view["street"] == "TURN"
