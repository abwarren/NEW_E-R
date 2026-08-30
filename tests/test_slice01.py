"""Slice 0 + 1 tests: foundation + snapshot tracer bullet.

Covers the directive's core requirements:
- /api/health responds
- POST /api/snapshot → persisted → GET /api/tables shows it
- stale/out-of-order snapshot → visible 409 (no silent loss, no deadlock)
- multi-table isolation (two tables, same player/browser)
- multi-bot isolation (two players/browsers, same table)
- hero seat stability across transient snapshots
- hand transition clears board/pot
- command queue roundtrip (create → claim → ack) + idempotency
- equity: PLO + holdem + invalid-card safety
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("ER_DB_URL", f"sqlite:///{tempfile.mkdtemp()}/test_state.db")
os.environ.setdefault("ER_PLAYERS_DB", f"{tempfile.mkdtemp()}/test_players.db")
os.environ.setdefault("ER_API_KEY", "test-key-123")

import pytest
from fastapi.testclient import TestClient

from backend.main import app, init_db as _app_init_db
from backend.players.db import PlayerDatabase
from backend.players.identity import IdentityService
from backend.state import StateStore
from backend.schemas import SnapshotPayload, SeatData

_app_init_db()  # TestClient does not run lifespan outside `with`; create tables now
client = TestClient(app)
H = {"X-API-Key": "test-key-123"}


@pytest.fixture(autouse=True)
def _clean_state():
    """Each test starts from an empty state DB (engine persists, data does not)."""
    from sqlalchemy import text

    from backend.db import session as db_session

    with db_session() as s:
        for t in ("events", "commands", "seat_snapshots", "equity_results", "table_state"):
            s.execute(text(f"DELETE FROM {t}"))
        s.commit()
    yield
    with db_session() as s:
        for t in ("events", "commands", "seat_snapshots", "equity_results", "table_state"):
            s.execute(text(f"DELETE FROM {t}"))
        s.commit()


def snap(**kw):
    base = dict(
        player_id="p1", browser_instance_id="b1", table_id="T1", hand_id="H1",
        snapshot_version=1, street="PRE_FLOP", pot=0, board=[],
        seats=[], hero_seat=-1, available_actions=["fold", "check", "call"],
        action_amounts={}, button_state="", table_state="SEATED", variant="plo",
    )
    base.update(kw)
    return base


def _register_player(player_id: str, username: str):
    db = PlayerDatabase(os.environ["ER_PLAYERS_DB"])
    try:
        try:
            db.get_player(player_id)
        except KeyError:
            db.create_player(username=username, player_id=player_id, display_name=username)
    finally:
        db.close()


def _seats(*names):
    return [SeatData(seat_no=i, name=n, stack=1000, is_hero=(n == "Hero"), bet=0, active=True) for i, n in enumerate(names)]


# ── slice 0: health ────────────────────────────────────────────────────────
def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_auth_required():
    assert client.get("/api/tables").status_code == 401
    assert client.get("/api/tables", headers=H).status_code == 200


# ── slice 1: snapshot tracer bullet ────────────────────────────────────────
def test_snapshot_roundtrip():
    _register_player("p1", "alice")
    r = client.post("/api/snapshot", json=snap(), headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["table_id"] == "T1"
    assert body["snapshot_version"] == 1

    tables = client.get("/api/tables", headers=H).json()
    assert any(t["table_id"] == "T1" for t in tables)
    assert all("password" not in str(t) for t in tables)

    one = client.get("/api/table/T1", params={"player_id": "p1", "browser_instance_id": "b1"}, headers=H).json()
    assert one["hand_id"] == "H1"
    assert one["street"] == "PRE_FLOP"


def test_stale_snapshot_rejected_visibly():
    _register_player("p1", "alice")
    client.post("/api/snapshot", json=snap(snapshot_version=5), headers=H)
    r = client.post("/api/snapshot", json=snap(snapshot_version=3), headers=H)
    assert r.status_code == 409
    assert "older" in r.json()["detail"]
    # ...and a newer snapshot still recovers (no deadlock)
    r2 = client.post("/api/snapshot", json=snap(snapshot_version=6, street="FLOP"), headers=H)
    assert r2.status_code == 200
    assert r2.json()["street"] == "FLOP"


# ── multi-table isolation ──────────────────────────────────────────────────
def test_two_tables_isolated():
    _register_player("p1", "alice")
    client.post("/api/snapshot", json=snap(table_id="T1", street="FLOP", pot=50), headers=H)
    client.post("/api/snapshot", json=snap(table_id="T2", street="PRE_FLOP", pot=0), headers=H)
    t1 = client.get("/api/table/T1", params={"player_id": "p1", "browser_instance_id": "b1"}, headers=H).json()
    t2 = client.get("/api/table/T2", params={"player_id": "p1", "browser_instance_id": "b1"}, headers=H).json()
    assert t1["pot"] == 50 and t1["street"] == "FLOP"
    assert t2["pot"] == 0 and t2["street"] == "PRE_FLOP"


# ── multi-bot isolation ────────────────────────────────────────────────────
def test_two_bots_same_table_isolated():
    _register_player("p1", "alice")
    _register_player("p2", "bob")
    client.post("/api/snapshot", json=snap(player_id="p1", browser_instance_id="b1", street="FLOP"), headers=H)
    client.post("/api/snapshot", json=snap(player_id="p2", browser_instance_id="b2", street="TURN"), headers=H)
    a = client.get("/api/table/T1", params={"player_id": "p1", "browser_instance_id": "b1"}, headers=H).json()
    b = client.get("/api/table/T1", params={"player_id": "p2", "browser_instance_id": "b2"}, headers=H).json()
    assert a["street"] == "FLOP" and a["player_id"] == "p1"
    assert b["street"] == "TURN" and b["player_id"] == "p2"
    # cross-browser lookup must not leak
    assert client.get("/api/table/T1", params={"player_id": "p1", "browser_instance_id": "b2"}, headers=H).status_code == 404


# ── hero seat stability ────────────────────────────────────────────────────
def test_hero_seat_survives_transient_absence():
    _register_player("p1", "alice")
    client.post("/api/snapshot", json=snap(snapshot_version=1, seats=[s.model_dump() for s in _seats("Hero", "Villain")], hero_seat=0), headers=H)
    # next snapshot: DOM flicker — hero flag missing, only villain visible
    client.post("/api/snapshot", json=snap(snapshot_version=2, seats=[SeatData(seat_no=1, name="Villain", stack=900).model_dump()], hero_seat=-1), headers=H)
    view = client.get("/api/table/T1", params={"player_id": "p1", "browser_instance_id": "b1"}, headers=H).json()
    assert view["hero_seat"] == 0, "hero seat must not be destroyed by transient DOM state"


def test_hand_transition_clears_board_and_pot():
    _register_player("p1", "alice")
    client.post("/api/snapshot", json=snap(snapshot_version=1, hand_id="H1", street="RIVER", pot=500, board=["As", "Ks", "Qs", "Js", "Ts"]), headers=H)
    client.post("/api/snapshot", json=snap(snapshot_version=2, hand_id="H2", street="PRE_FLOP", pot=30, board=["2c"]), headers=H)
    view = client.get("/api/table/T1", params={"player_id": "p1", "browser_instance_id": "b1"}, headers=H).json()
    assert view["hand_id"] == "H2"
    assert view["board"] == [], "new hand must clear the old board"
    assert view["pot"] == 30


# ── command queue roundtrip ────────────────────────────────────────────────
def test_command_roundtrip_and_idempotency():
    _register_player("p1", "alice")
    client.post("/api/snapshot", json=snap(), headers=H)
    r = client.post("/api/commands", json={
        "player_id": "p1", "browser_instance_id": "b1", "table_id": "T1", "hand_id": "H1",
        "action": "call", "amount": 20,
    }, headers=H)
    assert r.status_code == 200
    cid = r.json()["command_id"]
    assert r.json()["status"] == "QUEUED"

    claimed = client.get("/api/commands/pending", params={"player_id": "p1", "browser_instance_id": "b1"}, headers=H).json()
    assert claimed["command_id"] == cid
    assert claimed["status"] == "DELIVERED"
    # no double delivery
    again = client.get("/api/commands/pending", params={"player_id": "p1", "browser_instance_id": "b1"}, headers=H).json()
    assert again is None

    ack = client.post("/api/commands/ack", json={
        "command_id": cid, "player_id": "p1", "browser_instance_id": "b1", "status": "ACKNOWLEDGED",
    }, headers=H)
    assert ack.json()["status"] == "ACKNOWLEDGED"
    # repeat ACK = no-op
    ack2 = client.post("/api/commands/ack", json={
        "command_id": cid, "player_id": "p1", "browser_instance_id": "b1", "status": "ACKNOWLEDGED",
    }, headers=H)
    assert ack2.json()["status"] == "ACKNOWLEDGED"


def test_command_cannot_be_claimed_by_other_bot():
    _register_player("p1", "alice")
    _register_player("p2", "bob")
    client.post("/api/commands", json={
        "player_id": "p1", "browser_instance_id": "b1", "table_id": "T1", "action": "fold",
    }, headers=H)
    stolen = client.get("/api/commands/pending", params={"player_id": "p2", "browser_instance_id": "b2"}, headers=H).json()
    assert stolen is None


def test_unknown_action_rejected():
    r = client.post("/api/commands", json={
        "player_id": "p1", "browser_instance_id": "b1", "table_id": "T1", "action": "teleport",
    }, headers=H)
    assert r.status_code in (400, 422)  # explicit rejection either way


# ── equity ─────────────────────────────────────────────────────────────────
def test_equity_plo_aces_beat_deuces():
    r = client.post("/api/equity", json={
        "variant": "plo",
        # board gives AKQJ a broadway straight (A K Q J T); 2222 is just a pair
        "hands": [["As", "Ks", "Qh", "Jh"], ["2c", "2d", "2h", "2s"]],
        "board": ["Kd", "Qc", "Ts", "7h", "5d"],
        "samples": 500,
    }, headers=H)
    assert r.status_code == 200
    eq = r.json()
    assert not eq["error"]
    assert len(eq["equities"]) == 2
    assert eq["equities"][0] > 90  # broadway vs pair ≈ always
    assert abs(sum(eq["equities"]) - 100) < 2


def test_equity_holdem():
    r = client.post("/api/equity", json={
        "variant": "holdem",
        "hands": [["As", "Ah"], ["Kd", "Kc"]],
        "board": [],
        "samples": 500,
    }, headers=H)
    assert r.status_code == 200
    eq = r.json()
    assert not eq["error"]
    assert eq["equities"][0] > 60  # AA >> KK preflop


def test_equity_invalid_cards_fail_safely():
    r = client.post("/api/equity", json={
        "variant": "plo",
        "hands": [["As", "Ks", "Qh", "Jh"], ["2c", "2d", "2h", "2s"]],
        "board": ["Td", "9c", "3s", "7h", "XD"],  # invalid card
        "samples": 100,
    }, headers=H)
    assert r.status_code == 200
    assert r.json()["error"]
    assert r.json()["equities"] == []


# ── identity / isolation at the service layer ──────────────────────────────
def test_state_key_partition_never_collides():
    _register_player("p1", "alice")
    _register_player("p2", "bob")
    db = PlayerDatabase(os.environ["ER_PLAYERS_DB"])
    try:
        ia = db.register_browser_instance("p1", "browser-a")
        ib = db.register_browser_instance("p2", "browser-b")
        svc = IdentityService(db)
        k1 = svc.state_key("p1", ia.browser_instance_id, "T1", "H1", 1)
        k2 = svc.state_key("p2", ib.browser_instance_id, "T1", "H1", 1)
        assert k1.as_key() != k2.as_key()
    finally:
        db.close()
