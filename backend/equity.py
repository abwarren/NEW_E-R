"""E&R PokerBet — directional equity engine (eval7 in-process).

AUTHORITATIVE EQUITY CONTRACT:
- Every player is hero to himself; there is no table-level hero.
- For N players with known hole cards we produce N × (N-1) directional
  results (6 players ⇒ 30), each: hero → villain.
- RAW equity (broadcast truth): hero vs villain given ALL known cards —
  the other players' known hole cards are dead cards removed from the deck.
- REALIZED equity (hero perspective): hero's equity using ONLY hero hole
  cards + board + unknown opponent ranges — opponents' actual hole cards are
  NEVER used (they are not known to the hero).
- DISPARITY = realized − raw.

Pipeline: PokerBet cards → normalisation → validation → eval7 → structured
results. Invalid/impossible cards fail safely with a clear error.

Variants: PLO (default) and holdem. PLO evaluates the mean of the 6
(2-of-4 × 3-of-5) combos; holdem is standard 5-of-7 evaluation.
"""
from __future__ import annotations

import itertools
import random

import eval7

from .schemas import EquityRequest, EquityResult, DirectionalResult

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


def _hand_score(hand: list[str], board: list[str], variant: str) -> float:
    if variant == "plo":
        return _plo_combo_strength(hand, board)
    return float(eval7.evaluate([eval7.Card(c) for c in hand + board]))


def _mc_equity(
    hero: list[str], villain: list[str], board: list[str],
    dead: set[str], variant: str, samples: int, rng: random.Random,
) -> float:
    """Monte Carlo equity of hero vs villain given known dead cards.

    hero/villain are the two known hands; dead = every other known card
    (opponents' hole cards + board) removed from the deck.
    """
    used = set(hero) | set(villain) | dead
    deck = _deck_excluding(used)
    streets = 5 - len(board)
    wins = 0.0
    for _ in range(samples):
        rng.shuffle(deck)
        if streets > 0:
            board_full = board + deck[:streets]
        else:
            board_full = board
        hs = _hand_score(hero, board_full, variant)
        vs = _hand_score(villain, board_full, variant)
        if hs > vs:
            wins += 1.0
        elif hs == vs:
            wins += 0.5
    return round(wins / samples * 100, 2)


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
        n = len(hands)
        if n < 2:
            raise CardValidationError("need at least 2 hands for directional equity")
    except CardValidationError as e:
        return EquityResult(
            variant=req.variant, hands=req.hands, board=req.board,
            results=[], samples=0, error=str(e),
        )

    board_set = set(board)
    rng = random.Random()
    results: list[DirectionalResult] = []

    for h in range(n):
        hero = hands[h]
        others = [i for i in range(n) if i != h]
        for v in others:
            villain = hands[v]
            # RAW: hero vs villain with all other known cards dead
            dead = set()
            for i in range(n):
                if i != h and i != v:
                    dead |= set(hands[i])
            raw = _mc_equity(hero, villain, board, dead, req.variant, req.samples, rng)
            # REALIZED: hero's info-perspective — villain's cards are unknown;
            # treat villain as a random hand from the remaining deck (no dead
            # opponent cards, no villain cards known). We use the same MC but
            # with villain drawn from the deck each run.
            realized = _mc_equity_random_villain(hero, board, set(hands[h]) | board_set, req.variant, req.samples, rng)
            results.append(DirectionalResult(
                hero_index=h, villain_index=v,
                hero_cards=req.hands[h], villain_cards=req.hands[v],
                raw_equity=raw, realized_equity=realized,
                disparity=round(realized - raw, 2),
            ))

    return EquityResult(
        variant=req.variant, hands=req.hands, board=req.board,
        results=results, samples=req.samples,
    )


def _mc_equity_random_villain(
    hero: list[str], board: list[str], used: set[str],
    variant: str, samples: int, rng: random.Random,
) -> float:
    """Hero's realized equity vs an unknown villain hand drawn from the deck.

    used = hero's own cards + board (hero does NOT know opponents' cards).
    """
    deck = _deck_excluding(used)
    streets = 5 - len(board)
    wins = 0.0
    for _ in range(samples):
        rng.shuffle(deck)
        if streets > 0:
            board_full = board + deck[:streets]
            rest = deck[streets:]
        else:
            board_full = board
            rest = deck
        # villain = random hand from the remaining unknown cards
        if variant == "plo":
            villain = rest[:4]
        else:
            villain = rest[:2]
        hs = _hand_score(hero, board_full, variant)
        vs = _hand_score(villain, board_full, variant)
        if hs > vs:
            wins += 1.0
        elif hs == vs:
            wins += 0.5
    return round(wins / samples * 100, 2)
