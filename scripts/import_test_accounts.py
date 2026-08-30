#!/usr/bin/env python3
"""Register the four authorized PokerBet test accounts.

Reads ONLY the target usernames from the local Chrome vault (authorized
credential environment), decrypts via the OS-keyring Chrome Safe Storage key,
registers each account in the players DB with a unique player_id, and stores
the password in the OS keyring under service er-pokerbet.

NEVER prints, logs, or persists a password.
"""
from __future__ import annotations

import base64
import hashlib
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.players import credentials  # noqa: E402
from backend.players.chrome_import import (  # noqa: E402
    IV,
    LOGIN_DATA,
    _decrypt,
    _derive_aes_key,
    _get_safe_storage_key,
)
from backend.players.db import PlayerDatabase  # noqa: E402

TARGETS = ["Shickey", "Shangey", "Shanay", "Sergio"]


def read_target_rows(db_path: Path) -> list[tuple[str, bytes, str]]:
    """Read ONLY the target usernames' rows (no decryption, no printing)."""
    with tempfile.TemporaryDirectory(prefix="er-import-") as tmp:
        copy = Path(tmp) / "Login Data"
        shutil.copy2(db_path, copy)
        conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        try:
            placeholders = ",".join("?" for _ in TARGETS)
            rows = conn.execute(
                f"SELECT username_value, password_value, origin_url FROM logins"
                f" WHERE username_value IN ({placeholders})",
                TARGETS,
            ).fetchall()
        finally:
            conn.close()
    return [(r[0], bytes(r[1] or b""), r[2] or "") for r in rows]


def main() -> int:
    if not LOGIN_DATA.exists():
        print("Chrome Login Data not found at", LOGIN_DATA, file=sys.stderr)
        return 2

    rows = read_target_rows(LOGIN_DATA)
    found = {r[0] for r in rows}
    missing = [t for t in TARGETS if t not in found]
    print(f"vault entries found for {len(found)}/{len(TARGETS)} target accounts")
    if missing:
        print("NOT IN VAULT:", ", ".join(missing))

    if not rows:
        return 2  # external blocker: no credentials for these accounts

    # group by username (multiple rows possible); use the first non-empty pw
    best: dict[str, bytes] = {}
    for user, blob, _origin in rows:
        if blob and user not in best:
            best[user] = blob

    aes_key = _derive_aes_key(_get_safe_storage_key(), version="v11")
    db = PlayerDatabase()
    try:
        for user in TARGETS:
            blob = best.get(user)
            if not blob:
                print(f"  SKIP  {user}  (no password blob)")
                continue
            try:
                password = _decrypt(blob, aes_key)
            except Exception as e:
                print(f"  ERROR {user}  decrypt failed: {e}")
                continue
            if not password:
                print(f"  SKIP  {user}  (empty password)")
                continue
            player_id = user.lower()  # unique stable id
            try:
                try:
                    db.get_player(player_id)
                    action = "updated"
                except KeyError:
                    db.create_player(
                        username=user, player_id=player_id,
                        display_name=user, notes="PokerBet test account (authorized)",
                    )
                    action = "created"
                credentials.store_password(player_id, password)
                print(f"  OK    {user:<10} {action}  player_id={player_id}  cred=stored-in-keyring")
            except Exception as e:
                print(f"  ERROR {user}  {e}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
