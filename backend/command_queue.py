"""E&R PokerBet — command queue (state machine + idempotency).

Lifecycle:
    CREATED → QUEUED → DELIVERED → EXECUTING → ACKNOWLEDGED
                                      ↘ TIMEOUT → FAILED

Rules (from the project directive):
- every command carries player_id + browser_instance_id + table_id + hand_id;
  a command for one table/bot can never execute on another
- idempotent by command_id: duplicate delivery / duplicate ACK are no-ops
- a lost ACK must NOT re-execute on the browser: the extension tracks the last
  executed command_id and ignores repeats
- delivery is exclusive per (player, browser): only the owning browser's poll
  can claim a command
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from .config import settings
from .db import session
from .models import Command, Event
from .schemas import CommandCreate, CommandView
from .state import scope_key


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CommandQueue:
    # ── operator side ─────────────────────────────────────────────────────
    def create(self, req: CommandCreate) -> CommandView:
        if req.action not in {"fold", "check", "call", "bet", "raise", "all_in"}:
            if req.action not in {"cash_out", "show", "run_it_twice", "resume_hand", "back_to_game"}:
                raise ValueError(f"unsupported action: {req.action}")
        cmd_id = uuid.uuid4().hex[:16]
        with session() as s:
            cmd = Command(
                command_id=cmd_id,
                player_id=req.player_id,
                browser_instance_id=req.browser_instance_id,
                table_id=req.table_id,
                hand_id=req.hand_id,
                action=req.action,
                amount=req.amount,
                status="QUEUED",
            )
            s.add(cmd)
            s.add(
                Event(
                    type="command",
                    scope=scope_key(req.player_id, req.browser_instance_id, req.table_id),
                    payload=__import__("json").dumps(
                        {"command_id": cmd_id, "action": req.action, "amount": req.amount, "status": "QUEUED"}
                    ),
                )
            )
            s.commit()
            return self._view(cmd)

    def list(self, status: str | None = None, limit: int = 100) -> list[CommandView]:
        with session() as s:
            q = select(Command).order_by(Command.created_at.desc()).limit(limit)
            if status:
                q = q.where(Command.status == status)
            return [self._view(c) for c in s.execute(q).scalars().all()]

    def get(self, command_id: str) -> CommandView | None:
        with session() as s:
            c = s.get(Command, command_id)
            return self._view(c) if c else None

    # ── browser side ──────────────────────────────────────────────────────
    def claim_next(self, player_id: str, browser_instance_id: str) -> CommandView | None:
        """Atomically claim the oldest QUEUED command for this exact browser.

        Exclusive: only this (player, browser) can claim its own commands.
        """
        with session() as s:
            cmd = s.execute(
                select(Command)
                .where(
                    Command.player_id == player_id,
                    Command.browser_instance_id == browser_instance_id,
                    Command.status == "QUEUED",
                )
                .order_by(Command.created_at.asc())
                .limit(1)
            ).scalar_one_or_none()
            if cmd is None:
                return None
            # timeout any stale EXECUTING commands for this browser
            cutoff = _now() - timedelta(seconds=settings.command_timeout_seconds)
            s.execute(
                update(Command)
                .where(
                    Command.player_id == player_id,
                    Command.browser_instance_id == browser_instance_id,
                    Command.status == "EXECUTING",
                    Command.delivered_at < cutoff,
                )
                .values(status="TIMEOUT")
            )
            cmd.status = "DELIVERED"
            cmd.delivered_at = _now()
            cmd.attempts += 1
            s.add(
                Event(
                    type="command",
                    scope=scope_key(player_id, browser_instance_id, cmd.table_id),
                    payload=__import__("json").dumps(
                        {"command_id": cmd.command_id, "status": "DELIVERED"}
                    ),
                )
            )
            s.commit()
            return self._view(cmd)

    def ack(
        self,
        command_id: str,
        player_id: str,
        browser_instance_id: str,
        status: str = "ACKNOWLEDGED",
        error: str = "",
    ) -> CommandView:
        """Idempotent ACK: only CREATED→…/QUEUED/DELIVERED/EXECUTING rows move."""
        with session() as s:
            cmd = s.get(Command, command_id)
            if cmd is None:
                raise KeyError(f"unknown command: {command_id}")
            if cmd.player_id != player_id or cmd.browser_instance_id != browser_instance_id:
                raise PermissionError("command belongs to a different player/browser")
            if cmd.status in {"ACKNOWLEDGED", "FAILED", "TIMEOUT"}:
                return self._view(cmd)  # idempotent: repeat ACK is a no-op
            cmd.status = status
            cmd.acked_at = _now()
            cmd.error = error
            s.add(
                Event(
                    type="command",
                    scope=scope_key(player_id, browser_instance_id, cmd.table_id),
                    payload=__import__("json").dumps(
                        {"command_id": command_id, "action": cmd.action, "status": status, "error": error}
                    ),
                )
            )
            s.commit()
            return self._view(cmd)

    @staticmethod
    def _view(c: Command) -> CommandView:
        return CommandView(
            command_id=c.command_id,
            player_id=c.player_id,
            browser_instance_id=c.browser_instance_id,
            table_id=c.table_id,
            hand_id=c.hand_id,
            action=c.action,
            amount=c.amount,
            status=c.status,
            attempts=c.attempts,
            created_at=c.created_at.isoformat(),
        )
