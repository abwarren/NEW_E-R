"""E&R PokerBet — authoritative state store.

Eliminates the legacy failure modes:
- state duplication          → single row per (player, browser, table) scope
- multi-bot collision        → composite identity partition (StateKey)
- stale-snapshot deadlock    → version monotonicity; stale snapshot = visible 409,
                               never a permanent lock; newer snapshot always recovers
- silent snapshot loss       → every rejected snapshot returns an explicit error
- seat instability           → hero seat is sticky: transient absence does not
                               destroy the hero seat; seats merge by seat_no
- epoch deadlock             → no epoch machinery; version + hand_id + timestamp
- restart recovery           → state lives in the DB, resumes on boot
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from .db import session
from .models import Command, Event, SeatSnapshot, TableState
from .players.identity import IdentityService, StateKey
from .schemas import SeatData, SnapshotPayload, TableView

SCOPE_KEY_PREFIX = "player={p}|browser={b}|table={t}"


def scope_key(player_id: str, browser_instance_id: str, table_id: str) -> str:
    return SCOPE_KEY_PREFIX.format(p=player_id, b=browser_instance_id, t=table_id)


class StaleSnapshotError(Exception):
    def __init__(self, reason: str, current_version: int):
        super().__init__(reason)
        self.reason = reason
        self.current_version = current_version


class StateStore:
    def __init__(self, identity: IdentityService):
        self._identity = identity

    # ── ingestion ─────────────────────────────────────────────────────────
    def process_snapshot(self, payload: SnapshotPayload) -> TableView:
        key = self._identity.state_key(
            payload.player_id,
            payload.browser_instance_id,
            payload.table_id,
            payload.hand_id,
            payload.snapshot_version,
        )
        sk = scope_key(payload.player_id, payload.browser_instance_id, payload.table_id)

        with session() as s:
            row = s.execute(
                select(TableState).where(
                    TableState.player_id == payload.player_id,
                    TableState.browser_instance_id == payload.browser_instance_id,
                    TableState.table_id == payload.table_id,
                )
            ).scalar_one_or_none()

            now = datetime.now(timezone.utc)
            if row is not None:
                # Hand transition: a new hand starts preflop with an empty board
                # and fresh hole cards; the incoming pot (blinds) is kept.
                if payload.hand_id and row.hand_id and payload.hand_id != row.hand_id:
                    if payload.street == "PRE_FLOP":
                        payload.board = []
                    for seat in payload.seats:
                        seat.hole_cards = []
                        seat.bet = 0.0
                if payload.snapshot_version < row.snapshot_version:
                    raise StaleSnapshotError(
                        f"snapshot v{payload.snapshot_version} older than current v{row.snapshot_version} "
                        f"for {sk}",
                        row.snapshot_version,
                    )
                row.snapshot_version = payload.snapshot_version
                row.hand_id = payload.hand_id
                row.street = payload.street
                row.pot = payload.pot
                row.board = json.dumps(payload.board)
                row.seats = self._merge_seats(payload, row, now)
                row.hero_seat = self._resolve_hero(payload, row, now)
                row.available_actions = json.dumps(payload.available_actions)
                row.action_amounts = json.dumps(payload.action_amounts)
                row.button_state = payload.button_state
                row.table_state = payload.table_state
                row.is_stale = False
                row.updated_at = now
            else:
                row = TableState(
                    player_id=payload.player_id,
                    browser_instance_id=payload.browser_instance_id,
                    table_id=payload.table_id,
                    hand_id=payload.hand_id,
                    snapshot_version=payload.snapshot_version,
                    street=payload.street,
                    pot=payload.pot,
                    board=json.dumps(payload.board),
                    seats=json.dumps([seat.model_dump() for seat in payload.seats]),
                    hero_seat=payload.hero_seat,
                    available_actions=json.dumps(payload.available_actions),
                    action_amounts=json.dumps(payload.action_amounts),
                    button_state=payload.button_state,
                    table_state=payload.table_state,
                    updated_at=now,
                )
                s.add(row)
            s.flush()

            # Seat history (append-only) for hero-stability debugging.
            for seat in payload.seats:
                s.add(
                    SeatSnapshot(
                        scope=sk,
                        seat_no=seat.seat_no,
                        player_name=seat.name,
                        stack=seat.stack,
                        is_hero=seat.is_hero or (seat.seat_no == row.hero_seat),
                        hole_cards=json.dumps(seat.hole_cards),
                    )
                )
            s.add(
                Event(
                    type="snapshot",
                    scope=sk,
                    payload=json.dumps(
                        {
                            "version": payload.snapshot_version,
                            "hand": payload.hand_id,
                            "street": payload.street,
                            "pot": payload.pot,
                        }
                    ),
                )
            )
            s.commit()
            view = self._to_view(row)
            return view

    # ── hero-seat stability (legacy failure mode #9) ──────────────────────
    @staticmethod
    def _resolve_hero(payload: SnapshotPayload, row: TableState, now: datetime) -> int:
        incoming = [s for s in payload.seats if s.is_hero]
        if incoming:
            return incoming[0].seat_no
        # No hero flagged in this snapshot:
        # - transient DOM flicker → KEEP the previous hero seat (never destroy it)
        # - only an explicit leave/spectate state resets it
        if row.hero_seat >= 0 and payload.table_state not in ("LOBBY", "SPECTATING", ""):
            return row.hero_seat
        if payload.table_state in ("LOBBY", "SPECTATING"):
            return -1
        return row.hero_seat if row.hero_seat >= 0 else payload.hero_seat

    @staticmethod
    def _merge_seats(payload: SnapshotPayload, row: TableState, now: datetime) -> str:
        """Merge incoming seats by seat_no — never lose known players."""
        try:
            existing = json.loads(row.seats) if row.seats else []
        except json.JSONDecodeError:
            existing = []
        by_no = {s["seat_no"]: s for s in existing}
        for seat in payload.seats:
            prev = by_no.get(seat.seat_no, {})
            merged = seat.model_dump()
            # Preserve hole cards across brief DOM flickers when incoming is empty
            if not merged.get("hole_cards") and prev.get("hole_cards"):
                merged["hole_cards"] = prev["hole_cards"]
            by_no[seat.seat_no] = merged
        return json.dumps(list(by_no.values()))

    # ── reads ─────────────────────────────────────────────────────────────
    def list_tables(self, include_stale: bool = True) -> list[TableView]:
        with session() as s:
            q = select(TableState).order_by(TableState.updated_at.desc())
            if not include_stale:
                q = q.where(TableState.is_stale.is_(False))
            rows = s.execute(q).scalars().all()
            return [self._to_view(r) for r in rows]

    def get_table(self, player_id: str, browser_instance_id: str, table_id: str) -> TableView | None:
        sk = scope_key(player_id, browser_instance_id, table_id)
        with session() as s:
            row = s.execute(
                select(TableState).where(
                    TableState.player_id == player_id,
                    TableState.browser_instance_id == browser_instance_id,
                    TableState.table_id == table_id,
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            # SQLite returns naive datetimes; normalize before comparing.
            updated = row.updated_at
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - updated).total_seconds()
            if age > 30 and not row.is_stale:
                row.is_stale = True
                s.commit()
            view = self._to_view(row)
            view.is_stale = row.is_stale or age > 30
            return view

    @staticmethod
    def _to_view(row: TableState) -> TableView:
        try:
            seats = [SeatData(**x) for x in json.loads(row.seats or "[]")]
        except (json.JSONDecodeError, TypeError):
            seats = []
        hero_name = ""
        for seat in seats:
            if seat.seat_no == row.hero_seat:
                hero_name = seat.name
                break
        return TableView(
            player_id=row.player_id,
            browser_instance_id=row.browser_instance_id,
            table_id=row.table_id,
            hand_id=row.hand_id,
            snapshot_version=row.snapshot_version,
            street=row.street,
            pot=row.pot,
            board=json.loads(row.board or "[]"),
            seats=seats,
            hero_seat=row.hero_seat,
            hero_name=hero_name,
            available_actions=json.loads(row.available_actions or "[]"),
            action_amounts=json.loads(row.action_amounts or "{}"),
            button_state=row.button_state,
            table_state=row.table_state,
            is_stale=row.is_stale,
            updated_at=row.updated_at.isoformat(),
            scope_key=scope_key(row.player_id, row.browser_instance_id, row.table_id),
        )
