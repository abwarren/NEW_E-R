"""Multi-device deployment features: fleet staleness via list_tables + CORS default lockdown.

Covers the multi-device directive:
- /api/tables must mark a silently-disconnected device's table as stale (the
  fleet dashboard's ONLINE/OFFLINE status depends on this)
- include_stale=False hides stale tables
- CORS defaults to locked-down (no cross-origin browser access) unless
  ER_ALLOWED_ORIGINS is explicitly set; extension traffic bypasses CORS via
  manifest host permissions.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone

os.environ.setdefault("ER_DB_URL", f"sqlite:///{tempfile.mkdtemp()}/test_deploy.db")
os.environ.setdefault("ER_PLAYERS_DB", f"{tempfile.mkdtemp()}/test_deploy_players.db")
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


def _snap(player, browser, table, hand="H1", version=1, street="FLOP"):
    return {
        "player_id": player, "browser_instance_id": browser, "table_id": table,
        "hand_id": hand, "snapshot_version": version, "street": street, "pot": 10.0,
        "board": [], "seats": [], "hero_seat": -1,
        "available_actions": ["fold", "check"], "action_amounts": {},
        "button_state": "", "table_state": "SEATED", "variant": "plo",
    }


def _backdate(table_id: str, seconds: int = 60):
    from sqlalchemy import update
    from backend.db import session as db_session
    from backend.models import TableState
    with db_session() as s:
        s.execute(
            update(TableState)
            .where(TableState.table_id == table_id)
            .values(updated_at=datetime.now(timezone.utc) - timedelta(seconds=seconds))
        )
        s.commit()


# ── fleet staleness: silent disconnect surfaces in /api/tables ─────────────
def test_list_tables_marks_disconnected_device_stale():
    _players()
    client.post("/api/snapshot", json=_snap("p1", "b1", "T1"), headers=H)
    client.post("/api/snapshot", json=_snap("p2", "b2", "T2"), headers=H)
    # device A (p1/T1) stops sending; device B (p2/T2) keeps sending
    _backdate("T1", seconds=60)
    client.post("/api/snapshot", json=_snap("p2", "b2", "T2", version=2), headers=H)

    rows = client.get("/api/tables", headers=H).json()
    by_table = {r["table_id"]: r for r in rows}
    assert by_table["T1"]["is_stale"] is True, "silent device must surface as stale"
    assert by_table["T2"]["is_stale"] is False, "active device must stay live"

    # a fresh snapshot from the reconnected device clears the stale flag
    client.post("/api/snapshot", json=_snap("p1", "b1", "T1", version=2, street="TURN"), headers=H)
    rows = client.get("/api/tables", headers=H).json()
    assert {r["table_id"]: r for r in rows}["T1"]["is_stale"] is False


def test_list_tables_include_stale_false():
    from backend.state import StateStore
    from backend.players.identity import IdentityService

    _players()
    client.post("/api/snapshot", json=_snap("p1", "b1", "T1"), headers=H)
    _backdate("T1", seconds=60)
    store = StateStore(IdentityService(PlayerDatabase(os.environ["ER_PLAYERS_DB"])))
    assert [v.table_id for v in store.list_tables(include_stale=False)] == []


# ── CORS: locked down by default ───────────────────────────────────────────
def test_cors_locked_down_by_default():
    # preflight from a foreign origin is rejected outright
    r = client.options(
        "/api/health",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 400
    # simple cross-origin request gets no CORS headers
    r = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers
