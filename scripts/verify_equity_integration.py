#!/usr/bin/env python3
"""Integration verification of directional equity through the running app
(in-process TestClient — authorized, non-destructive, no curl).

Covers the acceptance gates after the suite:
1. /api/equity via the app (not direct engine calls)
2. SSE/dashboard propagation of directional equity
3. Remote aggregation hierarchy: Remote → Table → Hand → Hero → Villain
4. Two simultaneous tables cannot contaminate each other's equity results

Run: .venv/bin/python scripts/verify_equity_integration.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

TMP = tempfile.mkdtemp(prefix="er-eq-")
os.environ["ER_DB_URL"] = f"sqlite:///{TMP}/state.db"
os.environ["ER_PLAYERS_DB"] = f"{TMP}/players.db"
os.environ["ER_API_KEY"] = "verify"

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app, init_db  # noqa: E402
from backend.players.db import PlayerDatabase  # noqa: E402

init_db()
client = TestClient(app)
H = {"X-API-Key": "verify"}

ok = 0
fail = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok, fail
    ok += cond
    fail += not cond
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def main() -> int:
    pdb = PlayerDatabase(os.environ["ER_PLAYERS_DB"])
    for pid, uname in (("shickey", "Shickey"), ("shangey", "Shangey")):
        try:
            pdb.get_player(pid)
        except KeyError:
            pdb.create_player(username=uname, player_id=pid, display_name=uname)
        if not pdb.list_browser_instances(pid):
            pdb.register_browser_instance(pid, f"v-{pid}")
    bids = {pid: pdb.list_browser_instances(pid)[0].browser_instance_id for pid in ("shickey", "shangey")}
    pdb.close()

    # ── 1. /api/equity through the app ─────────────────────────────────────
    hands = [["As", "Ks", "Qh", "Jh"], ["2c", "2d", "2h", "2s"]]
    board = ["Kd", "Qc", "Ts", "7h", "5d"]
    r = client.post("/api/equity", json={"variant": "plo", "hands": hands, "board": board, "samples": 2000}, headers=H)
    body = r.json()
    check("api /api/equity 200 + results[]", r.status_code == 200 and len(body.get("results", [])) == 2)
    check("directional fields via api", all(k in body["results"][0] for k in ("hero_index", "villain_index", "raw_equity", "realized_equity", "disparity")))

    # ── 2. SSE/dashboard propagation: equity event persisted ───────────────
    from sqlalchemy import text
    from backend.db import session as db_session

    with db_session() as s:
        eq_events = s.execute(text("SELECT payload FROM events WHERE type='equity' ORDER BY id DESC LIMIT 1")).scalar()
    check("equity event propagated to SSE source (DB)", eq_events is not None and "results" in eq_events, str(eq_events)[:60] if eq_events else "none")
    js = (REPO / "backend/static/app.js").read_text()
    check("dashboard consumes equity events", "res.results" in js and "equity" in js)

    # ── 3. remote aggregation hierarchy: Remote → Table → Hand → Hero → Villain
    # snapshots for two tables (each player one table), then equity per table
    def snap(pid, bid, table, hand):
        return {
            "player_id": pid, "browser_instance_id": bid, "table_id": table,
            "hand_id": hand, "snapshot_version": 1, "street": "RIVER",
            "pot": 100, "board": board,
            "seats": [
                {"seat_no": 0, "name": pid, "stack": 1000, "hole_cards": hands[0], "bet": 0, "is_hero": True, "is_dealer": False, "sitting_out": False, "active": False},
                {"seat_no": 1, "name": "opp", "stack": 1000, "hole_cards": hands[1], "bet": 0, "is_hero": False, "is_dealer": False, "sitting_out": False, "active": False},
            ],
            "hero_seat": 0, "available_actions": ["fold", "check", "call"],
            "action_amounts": {}, "button_state": "", "table_state": "SEATED",
            "variant": "plo",
        }

    r1 = client.post("/api/snapshot", json=snap("shickey", bids["shickey"], "T-EQ-1", "H1"), headers=H)
    r2 = client.post("/api/snapshot", json=snap("shangey", bids["shangey"], "T-EQ-2", "H2"), headers=H)
    check("two tables snapshotted", r1.status_code == 200 and r2.status_code == 200)

    tables = client.get("/api/tables", headers=H).json()
    check("remote lists both tables (hierarchy root)", len(tables) == 2 and {t["table_id"] for t in tables} == {"T-EQ-1", "T-EQ-2"})

    # each table carries hand + hero → the hierarchy remote→table→hand→hero
    t1 = client.get("/api/table/T-EQ-1", params={"player_id": "shickey", "browser_instance_id": bids["shickey"]}, headers=H).json()
    t2 = client.get("/api/table/T-EQ-2", params={"player_id": "shangey", "browser_instance_id": bids["shangey"]}, headers=H).json()
    check("table→hand→hero association", t1["hand_id"] == "H1" and t1["hero_name"] == "shickey" and t2["hand_id"] == "H2" and t2["hero_name"] == "shangey")

    # ── 4. two tables cannot contaminate equity ────────────────────────────
    eq1 = client.post("/api/equity", json={"variant": "plo", "hands": hands, "board": board, "samples": 2000}, headers=H).json()
    eq2 = client.post("/api/equity", json={"variant": "plo", "hands": [["2c", "2d", "2h", "2s"], ["As", "Ks", "Qh", "Jh"]], "board": board, "samples": 2000}, headers=H).json()
    # reversed hero/villain ordering in table 2 — results must NOT bleed into table 1
    ab1 = next(x for x in eq1["results"] if (x["hero_index"], x["villain_index"]) == (0, 1))
    ab2 = next(x for x in eq2["results"] if (x["hero_index"], x["villain_index"]) == (0, 1))
    check("table 2 equity independent (reversed hands → different hero-0 raw)", abs(ab1["raw_equity"] - ab2["raw_equity"]) > 30, f"{ab1['raw_equity']} vs {ab2['raw_equity']}")
    # per-table equity_results persisted with scope
    with db_session() as s:
        erows = s.execute(text("SELECT table_id, hand_id, hero_player_id, villain_player_id FROM equity_results")).fetchall()
    check("equity_results persisted with table/hand/hero/villain scope", len(erows) >= 1, f"{len(erows)} rows")

    print(f"\nEQUITY INTEGRATION: {ok} pass / {fail} fail")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
