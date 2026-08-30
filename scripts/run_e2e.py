#!/usr/bin/env python3
"""E&R PokerBet — end-to-end acceptance harness (evidence-driven).

Maps the directive's 20-step acceptance test onto the real API, using two
simulated bot browsers (player→browser→table isolation), and writes evidence
to evidence/e2e/.

Run:  .venv/bin/python scripts/run_e2e.py
      ER_API_BASE=http://127.0.0.1:8090 ER_API_KEY=... .venv/bin/python scripts/run_e2e.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

API_BASE = os.environ.get("ER_API_BASE", "http://127.0.0.1:8090")
API_KEY = os.environ.get("ER_API_KEY", "er-dev-local")
EVIDENCE_DIR = REPO / "evidence" / "e2e"
INPROCESS = API_BASE == "inprocess"

if INPROCESS:
    os.environ.setdefault("ER_DB_URL", f"sqlite:///{REPO / 'data' / 'e2e_state.db'}")
    os.environ.setdefault("ER_PLAYERS_DB", f"{REPO / 'data' / 'e2e_players.db'}")
    os.environ.setdefault("ER_API_KEY", API_KEY)

try:
    import httpx
except ImportError:
    httpx = None

EVIDENCE: dict = {"steps": [], "ok": 0, "fail": 0}


def step(n: int, name: str, ok: bool, detail: str = "") -> None:
    EVIDENCE["steps"].append({"step": n, "name": name, "ok": ok, "detail": detail})
    EVIDENCE["ok" if ok else "fail"] += 1
    print(f"  [{n:>2}] {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def run() -> None:
    if INPROCESS:
        from fastapi.testclient import TestClient

        from backend.main import app, init_db

        init_db()
        tc = TestClient(app)
        client = tc  # httpx-compatible surface for our usage
    else:
        import httpx

        client = httpx.Client(base_url=API_BASE, headers={"X-API-Key": API_KEY}, timeout=10)

    def post(path, body):
        return client.post(path, json=body, headers={"X-API-Key": API_KEY})

    def get(path, **params):
        return client.get(path, params=params, headers={"X-API-Key": API_KEY})

    # ── 1-4. bot A opens PokerBet, table detected, identity created ────────
    r = get("/api/health")
    step(1, "backend healthy", r.status_code == 200 and r.json().get("status") == "ok")

    # two players (bots), each with one browser instance
    from backend.players.db import PlayerDatabase
    from backend.players.identity import IdentityService
    from backend.config import settings

    pdb = PlayerDatabase(settings.players_db)
    svc = IdentityService(pdb)
    bots = {}
    for pid, user in (("e2e_alice", "e2e_alice"), ("e2e_bob", "e2e_bob")):
        try:
            pdb.get_player(pid)
        except KeyError:
            pdb.create_player(username=user, player_id=pid, display_name=user)
        bid = pdb.register_browser_instance(pid, f"e2e-{user}") if not pdb.list_browser_instances(pid) else pdb.list_browser_instances(pid)[0]
        bots[pid] = bid.browser_instance_id
    pdb.close()
    step(2, "two players + browser instances registered", len(bots) == 2, ",".join(bots))

    def snap(player, browser, table, hand, version, street, pot, board, seats, actions):
        return {
            "player_id": player, "browser_instance_id": browser, "table_id": table,
            "hand_id": hand, "snapshot_version": version, "street": street, "pot": pot,
            "board": board, "seats": seats, "hero_seat": 0,
            "available_actions": actions, "action_amounts": {"call": 20, "raise": 60},
            "button_state": "", "table_state": "SEATED", "variant": "plo",
        }

    seats_a = [
        {"seat_no": 0, "name": "AliceBot", "stack": 980, "hole_cards": ["As", "Ks", "Qh", "Jh"], "bet": 10, "is_hero": True},
        {"seat_no": 1, "name": "VillainA", "stack": 1000, "hole_cards": [], "bet": 20},
    ]
    seats_b = [
        {"seat_no": 0, "name": "BobBot", "stack": 1000, "hole_cards": ["2c", "2d", "2h", "2s"], "bet": 5, "is_hero": True},
        {"seat_no": 1, "name": "VillainB", "stack": 900, "hole_cards": [], "bet": 5},
    ]

    # 5-10. bot A: hole cards, board, pot captured → snapshot → persisted
    r = post("/api/snapshot", snap("e2e_alice", bots["e2e_alice"], "E2E-T1", "H100", 1, "PRE_FLOP", 30, [], seats_a, ["fold", "check", "call"]))
    step(5, "hero/hole cards/state captured (alice preflop)", r.status_code == 200, r.text[:80])
    r = post("/api/snapshot", snap("e2e_alice", bots["e2e_alice"], "E2E-T1", "H100", 2, "FLOP", 60, ["Td", "9c", "3s"], seats_a, ["fold", "check", "call", "raise"]))
    step(6, "board captured (flop)", r.status_code == 200)
    r = get("/api/tables")
    tables = r.json()
    step(7, "snapshot persisted + listed", r.status_code == 200 and any(t["table_id"] == "E2E-T1" for t in tables))

    view = get("/api/table/E2E-T1", player_id="e2e_alice", browser_instance_id=bots["e2e_alice"]).json()
    step(8, "dashboard state correct", view["street"] == "FLOP" and view["pot"] == 60 and len(view["board"]) == 3)
    step(9, "hero seat + hole cards present", view["hero_seat"] == 0 and view["seats"][0]["hole_cards"] == ["As", "Ks", "Qh", "Jh"])

    # 12-13. equity for hero hand
    r = post("/api/equity", {"variant": "plo", "hands": [["As", "Ks", "Qh", "Jh"], ["2c", "2d", "2h", "2s"]], "board": ["Td", "9c", "3s", "7h", "5d"], "samples": 2000})
    eq = r.json()
    step(10, "equity calculated (eval7 in-process)", r.status_code == 200 and not eq.get("error") and len(eq.get("equities", [])) == 2, str(eq.get("equities")))

    # 14-19. operator → queue → claim → execute → ACK → state
    r = post("/api/commands", {"player_id": "e2e_alice", "browser_instance_id": bots["e2e_alice"], "table_id": "E2E-T1", "hand_id": "H100", "action": "call", "amount": 20})
    cid = r.json()["command_id"]
    step(11, "operator command queued", r.status_code == 200 and r.json()["status"] == "QUEUED")

    claimed = get("/api/commands/pending", player_id="e2e_alice", browser_instance_id=bots["e2e_alice"]).json()
    step(12, "correct browser claims command", claimed and claimed["command_id"] == cid)
    # wrong bot must NOT claim it
    stolen = get("/api/commands/pending", player_id="e2e_bob", browser_instance_id=bots["e2e_bob"]).json()
    step(13, "other bot cannot claim", stolen is None)

    r = post("/api/commands/ack", {"command_id": cid, "player_id": "e2e_alice", "browser_instance_id": bots["e2e_alice"], "status": "ACKNOWLEDGED"})
    step(14, "ACK reaches E&R", r.status_code == 200 and r.json()["status"] == "ACKNOWLEDGED")
    step(15, "pending empty after ACK", get("/api/commands/pending", player_id="e2e_alice", browser_instance_id=bots["e2e_alice"]).json() is None)

    # ── two tables / two bots isolation ─────────────────────────────────────
    post("/api/snapshot", snap("e2e_bob", bots["e2e_bob"], "E2E-T2", "H200", 1, "PRE_FLOP", 10, [], seats_b, ["fold", "check", "call"]))
    post("/api/snapshot", snap("e2e_bob", bots["e2e_bob"], "E2E-T2", "H200", 2, "TURN", 80, ["2s", "5c", "9d", "Kh"], seats_b, ["fold", "check", "call"]))
    a = get("/api/table/E2E-T1", player_id="e2e_alice", browser_instance_id=bots["e2e_alice"]).json()
    b = get("/api/table/E2E-T2", player_id="e2e_bob", browser_instance_id=bots["e2e_bob"]).json()
    ok_iso = a["street"] == "FLOP" and b["street"] == "TURN" and a["pot"] == 60 and b["pot"] == 80
    step(16, "two tables fully isolated", ok_iso, f"T1={a['street']}/{a['pot']} T2={b['street']}/{b['pot']}")

    # same table, two bots
    post("/api/snapshot", snap("e2e_bob", bots["e2e_bob"], "E2E-T1", "H300", 1, "PRE_FLOP", 10, [], seats_b, ["fold", "check"]))
    a2 = get("/api/table/E2E-T1", player_id="e2e_alice", browser_instance_id=bots["e2e_alice"]).json()
    b2 = get("/api/table/E2E-T1", player_id="e2e_bob", browser_instance_id=bots["e2e_bob"]).json()
    step(17, "two bots same table isolated", a2["street"] == "FLOP" and b2["street"] == "PRE_FLOP" and a2["pot"] == 60 and b2["pot"] == 10)

    # stale snapshot visible rejection
    r = post("/api/snapshot", snap("e2e_alice", bots["e2e_alice"], "E2E-T1", "H100", 1, "FLOP", 60, ["Td", "9c", "3s"], seats_a, []))
    step(18, "stale snapshot visibly rejected (409)", r.status_code == 409, r.text[:80])

    # write evidence
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "summary.json").write_text(json.dumps(EVIDENCE, indent=2))
    (EVIDENCE_DIR / "tables.json").write_text(json.dumps(get("/api/tables").json(), indent=2))
    (EVIDENCE_DIR / "commands.json").write_text(json.dumps(get("/api/commands").json(), indent=2))
    print(f"\nEVIDENCE → {EVIDENCE_DIR}")
    print(f"RESULT: {EVIDENCE['ok']} pass / {EVIDENCE['fail']} fail / 18 steps")
    sys.exit(1 if EVIDENCE["fail"] else 0)


if __name__ == "__main__":
    run()
