"""PokerBet player/bot account database (SQLite).

Stores ONLY account metadata. Passwords NEVER touch this database — they live in
the OS keyring (see ``backend/players/credentials.py``); SQLite keeps only a
credential reference (keyring service + key name).

Identity model (first-class, per project directive):
    player_id + browser_instance_id + table_id + hand_id + snapshot_version
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "players.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    player_id    TEXT PRIMARY KEY,
    username     TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL DEFAULT '',
    enabled      INTEGER NOT NULL DEFAULT 1,
    notes        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS browser_instances (
    browser_instance_id TEXT PRIMARY KEY,
    player_id           TEXT NOT NULL REFERENCES players(player_id),
    instance_label      TEXT NOT NULL DEFAULT '',
    last_seen_at        TEXT,
    enabled             INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_browser_player ON browser_instances(player_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass(frozen=True)
class Player:
    player_id: str
    username: str
    display_name: str
    enabled: bool
    notes: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        """Public dict — NEVER contains credentials."""
        return {
            "player_id": self.player_id,
            "username": self.username,
            "display_name": self.display_name,
            "enabled": self.enabled,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class BrowserInstance:
    browser_instance_id: str
    player_id: str
    instance_label: str
    last_seen_at: str | None
    enabled: bool
    created_at: str


class PlayerDatabase:
    """SQLite-backed player registry. Not thread-safe; one writer at a time."""

    def __init__(self, path: str | Path = DEFAULT_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # ── players ──────────────────────────────────────────────────────────
    def create_player(
        self,
        username: str,
        display_name: str = "",
        notes: str = "",
        player_id: str | None = None,
        enabled: bool = True,
    ) -> Player:
        username = username.strip()
        if not username:
            raise ValueError("username is required")
        pid = player_id or _new_id()
        ts = _now()
        try:
            self._conn.execute(
                "INSERT INTO players (player_id, username, display_name, enabled, notes, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pid, username, display_name, int(enabled), notes, ts, ts),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as e:
            raise ValueError(f"player already exists: {username}") from e
        return self.get_player(pid)

    def get_player(self, player_id: str) -> Player:
        row = self._conn.execute(
            "SELECT * FROM players WHERE player_id = ?", (player_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no such player: {player_id}")
        return self._row_to_player(row)

    def get_player_by_username(self, username: str) -> Player:
        row = self._conn.execute(
            "SELECT * FROM players WHERE username = ?", (username.strip(),)
        ).fetchone()
        if row is None:
            raise KeyError(f"no such player: {username}")
        return self._row_to_player(row)

    def list_players(self, include_disabled: bool = True) -> list[Player]:
        q = "SELECT * FROM players"
        if not include_disabled:
            q += " WHERE enabled = 1"
        q += " ORDER BY username"
        return [self._row_to_player(r) for r in self._conn.execute(q).fetchall()]

    def update_player(
        self,
        player_id: str,
        *,
        display_name: str | None = None,
        notes: str | None = None,
        enabled: bool | None = None,
    ) -> Player:
        self.get_player(player_id)  # exists?
        fields, vals = [], []
        if display_name is not None:
            fields.append("display_name = ?"); vals.append(display_name)
        if notes is not None:
            fields.append("notes = ?"); vals.append(notes)
        if enabled is not None:
            fields.append("enabled = ?"); vals.append(int(enabled))
        if not fields:
            return self.get_player(player_id)
        fields.append("updated_at = ?"); vals.append(_now())
        vals.append(player_id)
        self._conn.execute(
            f"UPDATE players SET {', '.join(fields)} WHERE player_id = ?", vals
        )
        self._conn.commit()
        return self.get_player(player_id)

    def set_enabled(self, player_id: str, enabled: bool) -> Player:
        return self.update_player(player_id, enabled=enabled)

    # ── browser instances (player-owned) ─────────────────────────────────
    def register_browser_instance(
        self,
        player_id: str,
        instance_label: str = "",
        browser_instance_id: str | None = None,
    ) -> BrowserInstance:
        """Every PokerBet browser MUST belong to exactly one player."""
        self.get_player(player_id)  # exists?
        bid = browser_instance_id or _new_id()
        ts = _now()
        self._conn.execute(
            "INSERT INTO browser_instances (browser_instance_id, player_id, instance_label, last_seen_at, enabled, created_at)"
            " VALUES (?, ?, ?, NULL, 1, ?)",
            (bid, player_id, instance_label, ts),
        )
        self._conn.commit()
        return self.get_browser_instance(bid)

    def get_browser_instance(self, browser_instance_id: str) -> BrowserInstance:
        row = self._conn.execute(
            "SELECT * FROM browser_instances WHERE browser_instance_id = ?",
            (browser_instance_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"no such browser instance: {browser_instance_id}")
        return BrowserInstance(
            browser_instance_id=row["browser_instance_id"],
            player_id=row["player_id"],
            instance_label=row["instance_label"],
            last_seen_at=row["last_seen_at"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
        )

    def list_browser_instances(self, player_id: str | None = None) -> list[BrowserInstance]:
        q = "SELECT * FROM browser_instances"
        args: tuple = ()
        if player_id is not None:
            q += " WHERE player_id = ?"
            args = (player_id,)
        q += " ORDER BY created_at"
        return [
            BrowserInstance(
                browser_instance_id=r["browser_instance_id"],
                player_id=r["player_id"],
                instance_label=r["instance_label"],
                last_seen_at=r["last_seen_at"],
                enabled=bool(r["enabled"]),
                created_at=r["created_at"],
            )
            for r in self._conn.execute(q, args).fetchall()
        ]

    def touch_browser_instance(self, browser_instance_id: str) -> None:
        self._conn.execute(
            "UPDATE browser_instances SET last_seen_at = ? WHERE browser_instance_id = ?",
            (_now(), browser_instance_id),
        )
        self._conn.commit()

    def set_browser_instance_enabled(self, browser_instance_id: str, enabled: bool) -> None:
        self._conn.execute(
            "UPDATE browser_instances SET enabled = ? WHERE browser_instance_id = ?",
            (int(enabled), browser_instance_id),
        )
        self._conn.commit()

    # ── helpers ───────────────────────────────────────────────────────────
    @staticmethod
    def _row_to_player(row: sqlite3.Row) -> Player:
        return Player(
            player_id=row["player_id"],
            username=row["username"],
            display_name=row["display_name"],
            enabled=bool(row["enabled"]),
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def close(self) -> None:
        self._conn.close()
