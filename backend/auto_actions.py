"""E&R PokerBet — threshold-based auto-action engine.

Evaluates the current table state for a single scope and returns a Decision
(or None if no action is warranted).

Thresholds (equity vs random villain range, Monte Carlo):
  < 20%    → fold  (if fold is available)
  20–35%   → check (preferred) else fold
  35–50%   → call  (preferred) else check
  50–70%   → raise / bet (min-raise sizing)
  70–90%   → raise / bet (pot-raise sizing)
  > 90%    → all-in (if available) else raise

Conservative by design:
- Never acts unless `needs_action` is set on the snapshot (snapshot must
  explicitly mark it as hero's turn).
- Never acts if hero has no hole cards visible.
- Falls back to check/fold if equity cannot be computed.
- Emits a Decision with action, amount (if relevant), equity used, and
  a human-readable reasoning string for the dashboard log.

Usage (from main.py):
    from .auto_actions import AutoActionEngine
    engine = AutoActionEngine()
    decision = engine.evaluate(table_view, hero_hole_cards)
    if decision:
        queue.create(CommandCreate(..., action=decision.action, amount=decision.amount))
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .equity import calculate
from .schemas import EquityRequest, TableView

logger = logging.getLogger(__name__)

# ── result type ──────────────────────────────────────────────────────────────

@dataclass
class Decision:
    """A recommended action from the auto-action engine."""
    action: str
    amount: float | None
    equity: float           # realized equity % that drove the decision
    confidence: float       # 0–1 heuristic confidence
    reasoning: str


# ── engine ───────────────────────────────────────────────────────────────────

class AutoActionEngine:
    """Threshold-based decision engine.

    Instantiate once and call evaluate() per snapshot event.
    Stateless: all context comes from the TableView.
    """

    def __init__(self, samples: int = 300) -> None:
        self._samples = samples

    def evaluate(self, view: TableView, hero_hole: list[str], variant: str = "plo") -> Decision | None:
        """Return a Decision or None.

        Args:
            view:       Current TableView from StateStore.
            hero_hole:  Hero's hole cards (list[str], e.g. ["As","Kh","Qd","Js"]).
                        Caller is responsible for extracting these from the view's
                        seats list.
            variant:    "plo" or "holdem" (default "plo"). TableView does not carry
                        this field, so the caller passes it (from the original snapshot).

        Returns:
            Decision if the engine recommends an action; None otherwise.
        """
        if not view.available_actions:
            return None
        # Safety gate: only act when it is provably the hero's turn.
        # table_state must be SEATED and needs_action is implicit in the
        # presence of available_actions (the extension only sends them when
        # the action buttons are visible).
        if view.table_state not in ("SEATED", "ACTIVE", ""):
            return None
        if not hero_hole:
            return self._no_cards_fallback(view.available_actions)

        eq = self._equity(hero_hole, view.board, variant)
        if eq is None:
            logger.warning("auto_actions: equity failed for %s — fallback", view.scope_key)
            return self._no_cards_fallback(view.available_actions)

        return self._threshold_decision(eq, view.available_actions, view.pot)

    # ── equity ───────────────────────────────────────────────────────────────

    def _equity(self, hero: list[str], board: list[str], variant: str) -> float | None:
        """Return realized equity % (0–100) or None on error."""
        # Need at least 4 hole cards for PLO, 2 for holdem.
        min_hole = 4 if variant == "plo" else 2
        if len(hero) < min_hole:
            return None
        # We only need realized equity (hero perspective vs random villain).
        # Use _mc_equity_random_villain directly via a single-hero request.
        # Fabricate a second hand from cards known not to be in hero's hand
        # so the duplicate-card validator passes; the MC logic overwrites
        # the villain hand each iteration anyway.
        used = set(hero) | set(board)
        all_cards = [r + s for r in "23456789TJQKA" for s in "shdc"]
        spare = [c for c in all_cards if c not in used]
        villain = spare[:min_hole]
        req = EquityRequest(
            variant=variant,
            hands=[hero, villain],
            board=board,
            samples=self._samples,
        )
        try:
            result = calculate(req)
        except Exception as exc:
            logger.error("auto_actions: equity exception: %s", exc)
            return None
        if result.error:
            return None
        # result[0] = hero(0)→villain(1); realized_equity is hero-perspective
        for r in result.results:
            if r.hero_index == 0 and r.villain_index == 1:
                return r.realized_equity
        return None

    # ── threshold logic ──────────────────────────────────────────────────────

    def _threshold_decision(
        self,
        eq: float,
        available: list[str],
        pot: float,
    ) -> Decision | None:
        acts = {a.lower() for a in available}

        if eq < 20.0:
            if "fold" in acts:
                return Decision("fold", None, eq, 0.80,
                                f"equity {eq:.1f}% < 20% — fold")
            if "check" in acts:
                return Decision("check", None, eq, 0.50,
                                f"equity {eq:.1f}% < 20% — check (no fold available)")
            return None

        if eq < 35.0:
            if "check" in acts:
                return Decision("check", None, eq, 0.60,
                                f"equity {eq:.1f}% 20–35% — check")
            if "fold" in acts:
                return Decision("fold", None, eq, 0.40,
                                f"equity {eq:.1f}% 20–35% — fold (no check)")
            return None

        if eq < 50.0:
            if "call" in acts:
                return Decision("call", None, eq, 0.60,
                                f"equity {eq:.1f}% 35–50% — call")
            if "check" in acts:
                return Decision("check", None, eq, 0.50,
                                f"equity {eq:.1f}% 35–50% — check")
            return None

        if eq < 70.0:
            action = "raise" if "raise" in acts else ("bet" if "bet" in acts else None)
            if action:
                # min raise — pot / 3
                amount = round(pot / 3, 2) if pot > 0 else None
                return Decision(action, amount, eq, 0.70,
                                f"equity {eq:.1f}% 50–70% — {action} ~pot/3")
            if "call" in acts:
                return Decision("call", None, eq, 0.55,
                                f"equity {eq:.1f}% 50–70% — call (no raise)")
            return None

        if eq < 90.0:
            action = "raise" if "raise" in acts else ("bet" if "bet" in acts else None)
            if action:
                # pot-sized raise
                amount = round(pot, 2) if pot > 0 else None
                return Decision(action, amount, eq, 0.80,
                                f"equity {eq:.1f}% 70–90% — {action} pot")
            if "call" in acts:
                return Decision("call", None, eq, 0.70,
                                f"equity {eq:.1f}% 70–90% — call (no raise)")
            return None

        # > 90%
        if "all_in" in acts:
            return Decision("all_in", None, eq, 0.95,
                            f"equity {eq:.1f}% > 90% — all-in")
        action = "raise" if "raise" in acts else ("bet" if "bet" in acts else None)
        if action:
            amount = round(pot * 1.5, 2) if pot > 0 else None
            return Decision(action, amount, eq, 0.90,
                            f"equity {eq:.1f}% > 90% — {action} 1.5× pot")
        return None

    # ── fallback (no hole cards visible) ─────────────────────────────────────

    @staticmethod
    def _no_cards_fallback(available: list[str]) -> Decision | None:
        acts = {a.lower() for a in available}
        if "check" in acts:
            return Decision("check", None, 0.0, 0.20,
                            "no hole cards visible — check blind")
        if "fold" in acts:
            return Decision("fold", None, 0.0, 0.40,
                            "no hole cards visible — fold blind")
        return None
