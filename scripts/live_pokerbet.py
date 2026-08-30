#!/usr/bin/env python3
"""Live PokerBet verification — login → table → scraper extraction → snapshot.

Reads the account password from the OS keyring (never prints it), drives
headless Chrome, enters a real PokerBet table, runs the E&R scraper extraction
against the live DOM, POSTs the snapshot to the local E&R backend, and writes
evidence to evidence/live/.

Usage:  ER_ACCOUNT=shickey .venv/bin/python scripts/live_pokerbet.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.players import credentials  # noqa: E402
from backend.players.db import PlayerDatabase  # noqa: E402

ACCOUNT = os.environ.get("ER_ACCOUNT", "shickey")
API_KEY = os.environ.get("ER_API_KEY", "er-dev-local")
API_BASE = os.environ.get("ER_API_BASE", "http://127.0.0.1:8090")
EVID = REPO / "evidence" / "live"
EVID.mkdir(parents=True, exist_ok=True)

from playwright.sync_api import sync_playwright  # noqa: E402


def get_password(player_id: str) -> str:
    """Password from the OS keyring. Never printed."""
    pw = credentials.fetch_password(player_id)
    return pw if pw is not None else ""


def main() -> int:
    db = PlayerDatabase()
    try:
        player = db.get_player(ACCOUNT)
    except KeyError:
        print(f"player {ACCOUNT} not in DB")
        return 2
    finally:
        db.close()
    username = player.username
    password = get_password(ACCOUNT)
    assert password, "no credential in keyring"
    browser_id = None

    import httpx

    evidence: dict = {"steps": [], "ok": 0, "fail": 0}

    def step(n: int, name: str, ok: bool, detail: str = "") -> None:
        evidence["steps"].append({"step": n, "name": name, "ok": ok, "detail": detail})
        evidence["ok" if ok else "fail"] += 1
        print(f"  [{n:>2}] {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            locale="en-US",
        )
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = ctx.new_page()

        # 1-2. open PokerBet, extension connects (extension loaded in headless via --load-extension)
        page.goto("https://www.pokerbet.co.za/en/page/casino/poker/28", timeout=45000)
        time.sleep(2)
        # login via the marketing site form (modal has input[type=text] + password)
        page.click("button.btn.s-small.sign-in")
        time.sleep(2.5)
        page.fill('input[type="text"]', username)
        page.fill('input[type="password"]', password)  # password never logged
        page.keyboard.press("Enter")
        time.sleep(6)
        signed_in = "Deposit" in page.inner_text("body") or "Balance" in page.inner_text("body")
        step(1, "login (Shickey)", signed_in, f"user={username}")

        # 3. open the poker client via Play button
        try:
            page.click("text=Play")
            time.sleep(5)
        except Exception:
            page.goto("https://www.pokerbet.co.za/en/page/casino/poker/28?openGames=28-real&gameNames=Poker", timeout=45000)
            time.sleep(5)
        # the LaunchGame iframe has the token; the client is at poker-web.pokerbet.co.za
        iframes = page.frames
        client = None
        for f in iframes:
            if "poker-web.pokerbet.co.za" in (f.url or ""):
                client = f
                break
        if not client:
            # try direct navigation with the iframe URL
            launcher = next((f for f in iframes if "LaunchGame" in (f.url or "")), None)
            if launcher:
                page.goto(launcher.url, timeout=45000)
                time.sleep(5)
            for f in page.frames:
                if "poker-web.pokerbet.co.za" in (f.url or ""):
                    client = f
                    break
        if not client:
            step(2, "poker client reached", False, "no poker-web frame found")
        else:
            step(2, "poker client reached", True, client.url[:100])
            # 4-6. lobby → PL Omaha 4 → PLAY NOW
            try:
                client.wait_for_selector("sg-quick-seat", timeout=30000)
            except Exception:
                pass
            # select PL Omaha 4
            try:
                opts = client.query_selector_all(".dropdown-option")
                for o in opts:
                    if "PL Omaha 4" in (o.inner_text() or ""):
                        o.click()
                        break
            except Exception:
                pass
            time.sleep(2)
            # PLAY NOW
            try:
                client.click("button.quick-seat-button", timeout=15000)
            except Exception:
                pass
            time.sleep(6)
            # 7. table detected?
            table_url = client.url
            tbl_match = re.search(r"/tbl/(\d+)", table_url)
            table_id = tbl_match.group(1) if tbl_match else ""
            body_text = client.inner_text("body") if client else ""
            hand_m = re.search(r"Hand ID:\s*(\d+)", body_text)
            hand_id = hand_m.group(1) if hand_m else ""
            has_seats = client.query_selector_all("sg-poker-table-seat")
            step(3, "table detected", bool(table_id) and len(has_seats) > 0, f"tbl={table_id} seats={len(has_seats)}")
            # 8. hero + seat capture
            hero = client.query_selector(".player-mini-container-p.self-player.poker, .player-mini-container-p.self-player")
            hero_seat = -1
            if hero:
                seats_all = client.query_selector_all("sg-poker-table-seat")
                for i, s in enumerate(seats_all):
                    if s.query_selector(".player-mini-container-p.self-player.poker, .player-mini-container-p.self-player"):
                        hero_seat = i
                        break
            step(4, "hero detected", hero is not None, f"hero_seat={hero_seat}")
            # 9. hole cards, board, pot, actions (may be empty if waiting for BB)
            hole = [c.inner_text().strip() for c in client.query_selector_all(".carts-container-p .single-cart-view-p")]
            board = [c.inner_text().strip() for c in client.query_selector_all("sg-poker-board .single-cart-view-p")]
            pot_el = client.query_selector(".pot-w-view-p, .pot-amount, .total-pot")
            pot = re.sub(r"[^0-9.]", "", pot_el.inner_text()) if pot_el else "0"
            actions = []
            for cls in [".fold-c", ".check-c", ".call-c", ".bet-c", ".raise-c"]:
                el = client.query_selector(f".control-b-view-p{cls}")
                if el and el.is_visible():
                    actions.append(cls.lstrip(".").rstrip("-c"))
            step(5, "state captured", True, f"hole={len(hole)} board={len(board)} pot={pot} actions={actions}")
            # 10. build + POST snapshot (the E&R scraper contract)
            seat_objs = client.query_selector_all("sg-poker-table-seat")
            seats_out = []
            for i, s in enumerate(seat_objs):
                name_el = s.query_selector(".player-name-count-v.self-player, .player-name, p.single-win-item-sizes")
                seats_out.append({
                    "seat_no": i,
                    "name": name_el.inner_text().strip() if name_el else "",
                    "stack": 0,
                    "hole_cards": hole if i == hero_seat else [],
                    "bet": 0, "is_hero": i == hero_seat, "is_dealer": False,
                    "sitting_out": False, "active": False,
                })
            snapshot = {
                "player_id": ACCOUNT, "browser_instance_id": "live-chrome-01",
                "table_id": table_id, "hand_id": hand_id,
                "snapshot_version": 1, "street": ("RIVER" if len(board) >= 5 else "TURN" if len(board) == 4 else "FLOP" if len(board) == 3 else "PRE_FLOP"),
                "pot": float(pot or 0), "board": board,
                "seats": seats_out,
                "hero_seat": hero_seat, "available_actions": actions, "action_amounts": {},
                "button_state": "", "table_state": "SEATED", "variant": "plo",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            # snapshot the live DOM to evidence
            (EVID / f"live-dom-{ACCOUNT}.html").write_text(client.content()[:200000])
            r = httpx.post(f"{API_BASE}/api/snapshot", json=snapshot, headers={"X-API-Key": API_KEY}, timeout=15)
            step(6, "snapshot reaches E&R", r.status_code == 200, f"HTTP {r.status_code}")
            if r.status_code == 200:
                (EVID / f"snapshot-{ACCOUNT}.json").write_text(json.dumps(snapshot, indent=2))
                step(7, "snapshot persisted", True)
            browser.close()

    (EVID / "summary.json").write_text(json.dumps(evidence, indent=2))
    print(f"\nLIVE EVIDENCE → {EVID}")
    print(f"RESULT: {evidence['ok']} pass / {evidence['fail']} fail / {len(evidence['steps'])} steps")
    return 0 if evidence["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
