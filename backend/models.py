"""E&R PokerBet — SQLAlchemy models.

State is partitioned by the composite identity mandated by the project
directive: player_id + browser_instance_id + table_id + hand_id + version.
This is the single source of truth (no JSON files, no duplicate in-memory
copies — legacy failure modes #3/#4 eliminated).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TableState(Base):
    """Authoritative live state for one (player, browser, table) scope.

    One row per scope; version is monotonic; older snapshots are rejected.
    """

    __tablename__ = "table_state"
    __table_args__ = (
        UniqueConstraint("player_id", "browser_instance_id", "table_id", name="uq_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[str] = mapped_column(String(64), index=True)
    browser_instance_id: Mapped[str] = mapped_column(String(64), index=True)
    table_id: Mapped[str] = mapped_column(String(128), index=True)
    hand_id: Mapped[str] = mapped_column(String(128), default="")
    snapshot_version: Mapped[int] = mapped_column(Integer, default=0)
    street: Mapped[str] = mapped_column(String(16), default="")
    pot: Mapped[float] = mapped_column(Float, default=0.0)
    board: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    seats: Mapped[str] = mapped_column(Text, default="[]")  # JSON list[SeatData]
    hero_seat: Mapped[int] = mapped_column(Integer, default=-1)
    available_actions: Mapped[str] = mapped_column(Text, default="[]")
    action_amounts: Mapped[str] = mapped_column(Text, default="{}")
    button_state: Mapped[str] = mapped_column(String(32), default="")
    table_state: Mapped[str] = mapped_column(String(32), default="")
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class SeatSnapshot(Base):
    """Seat history — append-only, for debugging/audit and hero-seat stability."""

    __tablename__ = "seat_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(256), index=True)  # StateKey.scope_key()
    seat_no: Mapped[int] = mapped_column(Integer)
    player_name: Mapped[str] = mapped_column(String(128), default="")
    stack: Mapped[float] = mapped_column(Float, default=0.0)
    is_hero: Mapped[bool] = mapped_column(Boolean, default=False)
    hole_cards: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Command(Base):
    """Command queue row. Lifecycle (state machine, ADR-003):

    CREATED → QUEUED → DELIVERED → EXECUTING → ACKNOWLEDGED
                                   ↘ TIMEOUT → FAILED
    Idempotent by command_id: duplicate delivery is a no-op.
    """

    __tablename__ = "commands"

    command_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    player_id: Mapped[str] = mapped_column(String(64), index=True)
    browser_instance_id: Mapped[str] = mapped_column(String(64), index=True)
    table_id: Mapped[str] = mapped_column(String(128), index=True)
    hand_id: Mapped[str] = mapped_column(String(128), default="")
    action: Mapped[str] = mapped_column(String(16))  # fold|check|call|bet|raise|all_in|...
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="CREATED", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Event(Base):
    """Event log — SSE replay + audit trail."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    scope: Mapped[str] = mapped_column(String(256), default="", index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class EquityResult(Base):
    __tablename__ = "equity_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(256), default="", index=True)
    variant: Mapped[str] = mapped_column(String(16), default="plo")
    hands: Mapped[str] = mapped_column(Text)  # JSON
    board: Mapped[str] = mapped_column(Text, default="[]")
    result: Mapped[str] = mapped_column(Text)  # JSON EquityResult
    samples: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
