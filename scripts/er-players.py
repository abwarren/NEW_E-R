#!/usr/bin/env python3
"""E&R PokerBet player/bot account CLI.

Passwords are NEVER printed. `register` reads from a prompt (hidden) or stdin;
the password goes straight into the OS keyring. All output is metadata only.

Examples:
    er-players.py register --username Danni1 --display-name "Danni"
    er-players.py import-chrome
    er-players.py list
    er-players.py disable <player_id>
    er-players.py check-credential <player_id>
    er-players.py add-browser <player_id> --label "kasm-01"
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.players import credentials  # noqa: E402
from backend.players.chrome_import import ChromeVaultUnavailable, import_from_chrome  # noqa: E402
from backend.players.db import PlayerDatabase  # noqa: E402
from backend.players.identity import IdentityService  # noqa: E402


def cmd_register(args: argparse.Namespace, db: PlayerDatabase) -> int:
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
        if not password:
            print("error: empty password on stdin", file=sys.stderr)
            return 1
    else:
        password = getpass.getpass(f"Password for {args.username}: ")
        if not password:
            print("error: empty password", file=sys.stderr)
            return 1
    try:
        player = db.create_player(
            username=args.username,
            display_name=args.display_name or args.username,
            notes=args.notes or "",
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    credentials.store_password(player.player_id, password)
    print(f"registered {player.player_id}  username={player.username}  display={player.display_name}")
    print("password stored in OS keyring (never in DB / logs / git)")
    return 0


def cmd_list(args: argparse.Namespace, db: PlayerDatabase) -> int:
    players = db.list_players(include_disabled=not args.enabled_only)
    if not players:
        print("no players registered")
        return 0
    for p in players:
        cred = "✔" if credentials.has_password(p.player_id) else "✘"
        print(
            f"{p.player_id}  {p.username:<24} {p.display_name:<20} "
            f"{'enabled' if p.enabled else 'DISABLED':<9} cred={cred}"
        )
    return 0


def cmd_show(args: argparse.Namespace, db: PlayerDatabase) -> int:
    p = db.get_player(args.player_id)
    for k, v in p.to_dict().items():
        print(f"{k}: {v}")
    print(f"credential: {'present in OS keyring' if credentials.has_password(p.player_id) else 'MISSING'}")
    insts = db.list_browser_instances(args.player_id)
    print(f"browser instances: {len(insts)}")
    for i in insts:
        print(
            f"  {i.browser_instance_id}  {i.instance_label}  "
            f"{'enabled' if i.enabled else 'DISABLED'}  last_seen={i.last_seen_at or '-'}"
        )
    return 0


def cmd_check_credential(args: argparse.Namespace, db: PlayerDatabase) -> int:
    p = db.get_player(args.player_id)
    if not p.enabled:
        print(f"player {args.player_id} is DISABLED — cannot be used")
        return 1
    pw = credentials.fetch_password(args.player_id)
    if pw is None:
        print(f"player {args.player_id}: NO credential in keyring")
        return 1
    # Verify round-trip without ever printing the value.
    ok = len(pw) > 0
    print(f"player {args.player_id}: credential present and retrievable ({'OK' if ok else 'EMPTY'})")
    return 0 if ok else 1


def cmd_set_enabled(args: argparse.Namespace, db: PlayerDatabase) -> int:
    p = db.update_player(args.player_id, enabled=args.enabled)
    print(f"player {p.player_id} now {'enabled' if p.enabled else 'disabled'}")
    return 0


def cmd_add_browser(args: argparse.Namespace, db: PlayerDatabase) -> int:
    inst = db.register_browser_instance(args.player_id, instance_label=args.label or "")
    print(f"browser instance {inst.browser_instance_id} registered for player {args.player_id}")
    return 0


def cmd_import_chrome(args: argparse.Namespace, db: PlayerDatabase) -> int:
    try:
        results = import_from_chrome(db, dry_run=args.dry_run)
    except ChromeVaultUnavailable as e:
        print(f"EXTERNAL BLOCKER: {e}", file=sys.stderr)
        return 2
    if not results:
        print("no pokerbet.co.za entries found in Chrome vault")
        return 0
    for r in results:
        print(f"{r.action:<8} {r.username:<28} {r.detail}")
    return 0


def cmd_verify_identity(args: argparse.Namespace, db: PlayerDatabase) -> int:
    """Sanity-check the isolation invariant for a player + browser pair."""
    svc = IdentityService(db)
    try:
        svc.resolve_browser(args.player_id, args.browser_instance_id)
    except (KeyError, PermissionError) as e:
        print(f"FAIL: {e}")
        return 1
    print("OK: browser instance owned by player, enabled")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="E&R PokerBet player accounts")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("register", help="register a player (password via hidden prompt or stdin)")
    p.add_argument("--username", required=True)
    p.add_argument("--display-name", default="")
    p.add_argument("--notes", default="")
    p.add_argument("--password-stdin", action="store_true", help="read password from stdin (no echo)")
    p.set_defaults(fn=cmd_register)

    p = sub.add_parser("list", help="list players (metadata only, no passwords)")
    p.add_argument("--enabled-only", action="store_true")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("show", help="show one player + browser instances")
    p.add_argument("player_id")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("check-credential", help="verify credential retrievable (never prints it)")
    p.add_argument("player_id")
    p.set_defaults(fn=cmd_check_credential)

    p = sub.add_parser("enable", help="enable a player")
    p.add_argument("player_id")
    p.set_defaults(fn=cmd_set_enabled, enabled=True)

    p = sub.add_parser("disable", help="disable a player (blocks use)")
    p.add_argument("player_id")
    p.set_defaults(fn=cmd_set_enabled, enabled=False)

    p = sub.add_parser("add-browser", help="register a browser instance for a player")
    p.add_argument("player_id")
    p.add_argument("--label", default="")
    p.set_defaults(fn=cmd_add_browser)

    p = sub.add_parser("import-chrome", help="import pokerbet.co.za accounts from Chrome vault (keyring path)")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_import_chrome)

    p = sub.add_parser("verify-identity", help="check player↔browser ownership")
    p.add_argument("player_id")
    p.add_argument("browser_instance_id")
    p.set_defaults(fn=cmd_verify_identity)

    args = ap.parse_args()
    db = PlayerDatabase()
    try:
        return args.fn(args, db)
    except (KeyError, PermissionError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
