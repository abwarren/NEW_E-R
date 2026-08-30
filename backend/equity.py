"""E&R PokerBet — equity engine (eval7 in-process, no HTTP hop).

Pipeline: PokerBet cards → normalisation → validation → eval7 → structured result.
Invalid/impossible card combinations fail safely with a clear error, never a crash.

Variants:
- PLO (default): each hand = 4 hole cards; equity = mean of the 6 (2-of-4 × 3-of-5)
  combos, Monte Carlo over the unknown deck.
- holdem: 2 hole cards, standard Monte Carlo.
"""
from __future__ import annotations

import itertools
import random

import eval7

from .schemas import EquityRequest, EquityResult

RANK_ORDER = "23456789TJQKA"
SUITS = "shdc"


class CardValidationError(ValueError):
    pass


def _norm_card(c: str) -> str:
    c = c.strip()
    if len(c) != 2:
        raise CardValidationError(f"invalid card: {c!r}")
    rank, suit = c[0].upper(), c[1].lower()
    if rank not in RANK_ORDER or suit not in SUITS:
        raise CardValidationError(f"invalid card: {c!r}")
    return rank + suit


def _norm_hand(hand: list[str], variant: str) -> list[str]:
    cards = [_norm_card(c) for c in hand]
    if len(cards) != len(set(cards)):
        raise CardValidationError(f"duplicate card in hand: {hand}")
    expect = 4 if variant == "plo" else 2
    if len(cards) != expect:
        raise CardValidationError(
            f"{variant} requires {expect} hole cards, got {len(cards)}: {hand}"
        )
    return cards


def _deck_excluding(used: set[str]) -> list[str]:
    return [r + s for r in RANK_ORDER for s in SUITS if r + s not in used]


def _plo_combo_strength(hole: list[str], board: list[str]) -> float:
    """Best eval7 score over the 6 Omaha combos (2 of 4 × 3 of 5).

    eval7 convention: HIGHER score = stronger hand.
    """
    best: float | None = None
    hole_cards = [eval7.Card(c) for c in hole]
    board_cards = [eval7.Card(c) for c in board]
    for h in itertools.combinations(hole_cards, 2):
        for b in itertools.combinations(board_cards, 3):
            score = eval7.evaluate(list(h) + list(b))
            if best is None or score > best:
                best = score
    assert best is not None  # hole=4, board=5 ⇒ combos are never empty
    return best


def calculate(req: EquityRequest) -> EquityResult:
    try:
        hands = [_norm_hand(h, req.variant) for h in req.hands]
        board = [_norm_card(c) for c in req.board]
        all_cards = [c for h in hands for c in h] + board
        if len(all_cards) != len(set(all_cards)):
            raise CardValidationError("cards overlap between hands/board")
        if req.variant == "plo":
            if len(board) != 5:
                raise CardValidationError("PLO equity requires a full 5-card board")
        else:
            if len(board) not in (0, 3, 4, 5):
                raise CardValidationError("holdem board must have 0, 3, 4 or 5 cards")
    except CardValidationError as e:
        return EquityResult(
            variant=req.variant, hands=req.hands, board=req.board,
            equities=[], samples=0, error=str(e),
        )

    used = set(all_cards)
    deck = _deck_excluding(used)
    rng = random.Random()
    wins = [0.0] * len(hands)
    samples = req.samples

    for _ in range(samples):
        rng.shuffle(deck)
        idx = 0
        streets = 5 - len(board)
        if streets > 0:
            board_full = board + deck[idx : idx + streets]
            idx += streets
        else:
            board_full = board
        scores = []
        for hand in hands:
            cards = [eval7.Card(c) for c in hand + board_full]
            if req.variant == "plo":
                scores.append(_plo_combo_strength(hand, board_full))
            else:
                scores.append(float(eval7.evaluate(cards)))
        best = max(scores)
        winners = [i for i, sc in enumerate(scores) if sc == best]
        for w in winners:
            wins[w] += 1.0 / len(winners)

    equities = [round(w / samples * 100, 2) for w in wins]
    return EquityResult(
        variant=req.variant, hands=req.hands, board=req.board,
        equities=equities, samples=samples,
    )
