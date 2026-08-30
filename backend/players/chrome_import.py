"""Import PokerBet credentials from the local Chrome password vault.

This is the *authorized* path the user pointed at
(``chrome://password-manager/passwords/pokerbet.co.za?q=poker``):

1. Chrome stores encrypted passwords in ``~/.config/google-chrome/Default/Login Data``.
2. The encryption key ("Chrome Safe Storage") lives in the OS keyring — the same
   keyring this application uses. We are the user's own process reading the
   user's own keyring; nothing is bypassed or cracked.
3. We decrypt ONLY entries whose origin/action URL matches pokerbet.co.za,
   register the player account in SQLite (metadata only), and store the
   password in the OS keyring under service ``er-pokerbet``.

Passwords are never printed, logged, or written to disk outside the keyring.
"""
from __future__ import annotations

import base64
import hashlib
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from . import credentials
from .db import PlayerDatabase

CHROME_PROFILE = Path.home() / ".config" / "google-chrome" / "Default"
LOGIN_DATA = CHROME_PROFILE / "Login Data"
SAFE_STORAGE_LABEL = "Chrome Safe Storage"
AES_KEY_SALT = b"saltysalt"
PBKDF2_ITERATIONS = 1
AES_KEY_LEN = 16
IV = b" " * 16


class ChromeVaultUnavailable(Exception):
    """Raised when the Chrome vault or its keyring key cannot be read."""


@dataclass(frozen=True)
class ChromeLogin:
    username: str
    encrypted_password: bytes
    origin_url: str


@dataclass(frozen=True)
class ImportResult:
    username: str
    action: str  # 'created' | 'updated' | 'skipped' | 'error'
    detail: str = ""


def _get_safe_storage_key() -> bytes:
    """Read the Chrome Safe Storage key from the OS keyring (Secret Service)."""
    try:
        import secretstorage

        bus = secretstorage.dbus_init()
        collection = secretstorage.get_default_collection(bus)
        collection.unlock()
        for item in collection.get_all_items():
            attrs = item.get_attributes()
            if item.get_label() == SAFE_STORAGE_LABEL or attrs.get("application") == "chrome":
                return bytes(item.get_secret())
    except Exception as e:  # pragma: no cover - environment dependent
        raise ChromeVaultUnavailable(f"could not read Chrome Safe Storage key: {e}") from e
    raise ChromeVaultUnavailable("Chrome Safe Storage key not found in OS keyring")


def _derive_aes_key(safe_storage_value: bytes, version: str = "v10") -> bytes:
    """Derive the AES key. The keyring value may be raw bytes or base64.

    Chrome v10: PBKDF2 iterations=1. Chrome v11 (v11-prefixed blobs): 1003.
    """
    candidates = [safe_storage_value]
    try:
        candidates.append(base64.b64decode(safe_storage_value, validate=True))
    except Exception:
        pass
    iterations = 1003 if version == "v11" else 1
    for c in candidates:
        if len(c) >= AES_KEY_LEN:
            return hashlib.pbkdf2_hmac(
                "sha1", c, AES_KEY_SALT, iterations, dklen=AES_KEY_LEN
            )
    raise ChromeVaultUnavailable("unusable Chrome Safe Storage key material")


def _decrypt(encrypted: bytes, aes_key: bytes) -> str:
    payload = encrypted
    if payload[:3] in (b"v10", b"v11"):
        payload = payload[3:]
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(IV))
    dec = cipher.decryptor()
    plain = dec.update(payload) + dec.finalize()
    # PKCS7 padding: last byte(s) are the pad length
    pad = plain[-1] if plain else 0
    if 1 <= pad <= 16:
        plain = plain[:-pad]
    return plain.decode("utf-8", errors="replace")


def _read_login_rows(db_path: Path) -> list[ChromeLogin]:
    """Read pokerbet.co.za rows from a copy of Chrome's Login Data."""
    with tempfile.TemporaryDirectory(prefix="chrome-import-tmp-") as tmp:
        copy = Path(tmp) / "Login Data"
        shutil.copy2(db_path, copy)
        conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT origin_url, action_url, username_value, password_value"
                " FROM logins"
                " WHERE origin_url LIKE '%pokerbet%' OR action_url LIKE '%pokerbet%'"
                " ORDER BY username_value"
            ).fetchall()
        finally:
            conn.close()
    out = []
    for r in rows:
        username = (r["username_value"] or "").strip()
        if not username:
            continue
        out.append(
            ChromeLogin(
                username=username,
                encrypted_password=bytes(r["password_value"] or b""),
                origin_url=r["origin_url"] or "",
            )
        )
    return out


def import_from_chrome(
    db: PlayerDatabase,
    *,
    login_data: Path | None = None,
    safe_storage_key: bytes | None = None,
    dry_run: bool = False,
) -> list[ImportResult]:
    """Import all pokerbet.co.za accounts from the local Chrome vault.

    Returns per-account results. Never prints or returns passwords.
    """
    login_data = login_data or LOGIN_DATA
    if not login_data.exists():
        raise ChromeVaultUnavailable(f"Chrome Login Data not found at {login_data}")

    aes_key = _derive_aes_key(safe_storage_key if safe_storage_key is not None else _get_safe_storage_key())
    logins = _read_login_rows(login_data)

    results: list[ImportResult] = []
    for login in logins:
        try:
            password = _decrypt(login.encrypted_password, aes_key)
        except Exception as e:
            results.append(ImportResult(login.username, "error", f"decrypt failed: {e}"))
            continue
        if not password:
            results.append(ImportResult(login.username, "skipped", "empty password"))
            continue
        if dry_run:
            results.append(ImportResult(login.username, "skipped", "dry-run (would import)"))
            continue
        try:
            player = db.get_player_by_username(login.username)
            # metadata may need display-name/notes refresh; cred is refreshed below
            action = "updated"
        except KeyError:
            player = db.create_player(
                username=login.username,
                display_name=login.username,
                notes="imported from Chrome password manager",
            )
            action = "created"
        credentials.store_password(player.player_id, password)
        results.append(ImportResult(login.username, action, "credential stored in OS keyring"))
    return results
