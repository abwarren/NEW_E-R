"""Composite identity for E&R state.

The project directive requires that one player's credentials, browser session,
table state, commands and equity data can never be confused with another
player's. State is therefore keyed by:

    player_id + browser_instance_id + table_id + hand_id + snapshot_version

This module provides the StateKey value object and the ownership checks that
enforce the isolation invariant (a browser instance belongs to exactly one
player; a state key must reference a browser the player actually owns).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .db import PlayerDatabase


@dataclass(frozen=True, order=True)
class StateKey:
    player_id: str
    browser_instance_id: str
    table_id: str
    hand_id: str = ""
    snapshot_version: int = 0

    def as_key(self) -> str:
        """Canonical composite key for dict/DB indexing."""
        return (
            f"player={self.player_id}|browser={self.browser_instance_id}"
            f"|table={self.table_id}|hand={self.hand_id}|v={self.snapshot_version}"
        )

    def scope_key(self) -> str:
        """Key for state that is per-table but hand-independent (e.g. seats)."""
        return f"player={self.player_id}|browser={self.browser_instance_id}|table={self.table_id}"

    def is_valid(self) -> bool:
        return bool(self.player_id and self.browser_instance_id and self.table_id)


class IdentityService:
    """Enforces player→browser ownership and resolves StateKeys."""

    def __init__(self, db: PlayerDatabase):
        self._db = db

    def resolve_browser(self, player_id: str, browser_instance_id: str) -> None:
        """Raise if the browser instance does not belong to the player."""
        inst = self._db.get_browser_instance(browser_instance_id)
        if inst.player_id != player_id:
            raise PermissionError(
                f"browser {browser_instance_id} belongs to player "
                f"{inst.player_id}, not {player_id} — cross-player access blocked"
            )
        if not inst.enabled:
            raise PermissionError(f"browser instance disabled: {browser_instance_id}")

    def require_player_enabled(self, player_id: str) -> None:
        player = self._db.get_player(player_id)
        if not player.enabled:
            raise PermissionError(f"player disabled: {player_id}")

    def state_key(
        self,
        player_id: str,
        browser_instance_id: str,
        table_id: str,
        hand_id: str = "",
        snapshot_version: int = 0,
    ) -> StateKey:
        """Build a StateKey, enforcing player↔browser ownership first."""
        self.require_player_enabled(player_id)
        self.resolve_browser(player_id, browser_instance_id)
        if not table_id:
            raise ValueError("table_id is required")
        return StateKey(
            player_id=player_id,
            browser_instance_id=browser_instance_id,
            table_id=table_id,
            hand_id=hand_id,
            snapshot_version=snapshot_version,
        )
