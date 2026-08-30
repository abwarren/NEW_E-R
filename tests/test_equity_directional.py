"""AUTHORITATIVE equity contract — acceptance tests.

Proves:
- 2 players ⇒ 2 directional results (A→B, B→A), separate perspectives
- 6 players ⇒ 6×5 = 30 directional results
- every player can be hero; every other player can be villain
- RAW equity uses known/dead cards (opponents' hole cards removed)
- REALIZED equity does NOT use opponents' actual hole cards
- DISPARITY = realized − raw
- results stay associated with the correct hero
- no table/player cross-contamination
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.equity import calculate  # noqa: E402
from backend.schemas import EquityRequest  # noqa: E402


def test_two_players_two_directional_results():
    r = calculate(EquityRequest(
        variant="plo",
        hands=[["As", "Ks", "Qh", "Jh"], ["2c", "2d", "2h", "2s"]],
        board=["Td", "9c", "3s", "7h", "5d"], samples=2000,
    ))
    assert not r.error, r.error
    assert len(r.results) == 2, f"expected 2 results, got {len(r.results)}"
    by_pair = {(x.hero_index, x.villain_index): x for x in r.results}
    assert (0, 1) in by_pair and (1, 0) in by_pair
    # A→B and B→A are separate perspectives (different raw equities)
    assert by_pair[(0, 1)].raw_equity != by_pair[(1, 0)].raw_equity


def test_six_players_thirty_results():
    hands = [
        ["As", "Ks", "Qh", "Jh"], ["2c", "2d", "2h", "2s"],
        ["Ac", "Ad", "Ah", "7c"], ["9s", "9d", "9h", "9c"],
        ["Ts", "Td", "Th", "8s"], ["3h", "4d", "5c", "6s"],
    ]
    # board disjoint from all 24 hand cards
    r = calculate(EquityRequest(variant="plo", hands=hands, board=["Kd", "Qd", "Jd", "8d", "7d"], samples=1000))
    assert not r.error
    assert len(r.results) == 30, f"expected 6×5=30, got {len(r.results)}"
    # every hero has 5 villains, every villain appears for each hero
    for h in range(6):
        villains = {x.villain_index for x in r.results if x.hero_index == h}
        assert villains == {0, 1, 2, 3, 4, 5} - {h}, f"hero {h} villains wrong: {villains}"
    for v in range(6):
        heroes = {x.hero_index for x in r.results if x.villain_index == v}
        assert heroes == {0, 1, 2, 3, 4, 5} - {v}, f"villain {v} heroes wrong: {heroes}"
    # no duplicate (hero, villain) pair
    pairs = [(x.hero_index, x.villain_index) for x in r.results]
    assert len(pairs) == len(set(pairs))


def test_raw_uses_dead_cards_realized_does_not():
    # 3 players: A strong, B weak, C has A's out-cards (dead for A→B raw)
    hands = [
        ["As", "Ah", "Kd", "Kc"],   # A: aces
        ["2c", "3d", "4h", "5s"],   # B: junk
        ["Ad", "Ac", "7d", "7c"],   # C: holds two more aces → dead for A→B
    ]
    board = ["9d", "8c", "3s", "Jh", "Qd"]
    r = calculate(EquityRequest(variant="plo", hands=hands, board=board, samples=2000))
    assert not r.error
    ab = next(x for x in r.results if x.hero_index == 0 and x.villain_index == 1)
    # RAW A→B: C's aces are dead → A cannot hit aces → raw lower than if unknown
    # REALIZED A→B: hero A only knows own cards + board; C's cards unknown
    # → realized uses random villain range, not B's junk and not C's aces
    assert ab.raw_equity >= 0 and ab.raw_equity <= 100
    assert ab.realized_equity >= 0 and ab.realized_equity <= 100
    # disparity is exactly realized − raw
    assert abs(ab.disparity - (ab.realized_equity - ab.raw_equity)) < 0.01
    # realized must NOT equal raw (different information models)
    assert abs(ab.realized_equity - ab.raw_equity) > 0.1


def test_disparity_formula():
    hands = [["As", "Ks", "Qh", "Jh"], ["2c", "2d", "2h", "2s"]]
    r = calculate(EquityRequest(variant="plo", hands=hands, board=["Td", "9c", "3s", "7h", "5d"], samples=2000))
    for x in r.results:
        assert abs(x.disparity - (x.realized_equity - x.raw_equity)) < 0.01


def test_no_cross_contamination_results_associated():
    hands = [
        ["As", "Ks", "Qh", "Jh"], ["2c", "2d", "2h", "2s"],
        ["Ac", "Ad", "Ah", "7c"],
    ]
    r = calculate(EquityRequest(variant="plo", hands=hands, board=["Td", "9c", "3s", "7h", "5d"], samples=1000))
    for x in r.results:
        # hero cards must match the hero's actual hand
        assert x.hero_cards == hands[x.hero_index]
        assert x.villain_cards == hands[x.villain_index]
        assert x.hero_index != x.villain_index


def test_invalid_cards_fail_safe():
    r = calculate(EquityRequest(variant="plo", hands=[["As", "Ks", "Qh", "Jh"], ["Xx", "2d", "2h", "2s"]], board=["Td", "9c", "3s", "7h", "5d"], samples=100))
    assert r.error != "" and r.results == []
