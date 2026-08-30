"""E&R PokerBet — interface contracts (Pydantic schemas).

Contract-first: every layer (extension, API, service, equity engine) speaks
these shapes. See docs/CONTRACTS.md for the governing document.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Action = Literal[
    "fold", "check", "call", "bet", "raise", "all_in",
    "cash_out", "show", "run_it_twice", "resume_hand", "back_to_game",
]

Street = Literal["", "PRE_FLOP", "FLOP", "TURN", "RIVER", "HAND_COMPLETE", "SHOWDOWN"]


class SeatData(BaseModel):
    seat_no: int
    name: str = ""
    stack: float = 0.0
    hole_cards: list[str] = Field(default_factory=list)
    bet: float = 0.0
    is_hero: bool = False
    is_dealer: bool = False
    sitting_out: bool = False
    active: bool = False


class SnapshotPayload(BaseModel):
    """The one contract the PokerBet scraper (w4p.js) sends."""

    player_id: str = Field(min_length=1)
    browser_instance_id: str = Field(min_length=1)
    table_id: str = Field(min_length=1)
    hand_id: str = ""
    snapshot_version: int = 0
    street: Street = ""
    pot: float = 0.0
    board: list[str] = Field(default_factory=list)
    seats: list[SeatData] = Field(default_factory=list)
    hero_seat: int = -1
    available_actions: list[Action] = Field(default_factory=list)
    action_amounts: dict[str, float] = Field(default_factory=dict)
    button_state: str = ""
    table_state: str = ""
    variant: Literal["plo", "holdem"] = "plo"
    timestamp: str = ""

    @field_validator("board", "seats")
    @classmethod
    def _no_none(cls, v):
        return v or []


class TableView(BaseModel):
    """What the dashboard sees — never contains credentials."""

    player_id: str
    browser_instance_id: str
    table_id: str
    hand_id: str
    snapshot_version: int
    street: str
    pot: float
    board: list[str]
    seats: list[SeatData]
    hero_seat: int
    hero_name: str = ""
    available_actions: list[str]
    action_amounts: dict[str, float]
    button_state: str
    table_state: str
    is_stale: bool
    updated_at: str
    scope_key: str


class CommandCreate(BaseModel):
    player_id: str = Field(min_length=1)
    browser_instance_id: str = Field(min_length=1)
    table_id: str = Field(min_length=1)
    hand_id: str = ""
    action: Action
    amount: float | None = None


class CommandView(BaseModel):
    command_id: str
    player_id: str
    browser_instance_id: str
    table_id: str
    hand_id: str
    action: str
    amount: float | None
    status: str
    attempts: int
    created_at: str


class CommandAck(BaseModel):
    command_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    browser_instance_id: str = Field(min_length=1)
    status: Literal["ACKNOWLEDGED", "FAILED", "TIMEOUT"] = "ACKNOWLEDGED"
    error: str = ""


class EquityRequest(BaseModel):
    variant: Literal["plo", "holdem"] = "plo"
    hands: list[list[str]] = Field(min_length=2, max_length=6)
    board: list[str] = Field(default_factory=list)
    samples: int = Field(default=2000, ge=100, le=100000)


class DirectionalResult(BaseModel):
    """One hero→villain directional equity result (the fundamental object).

    raw_equity      = broadcast-known true equity (all known cards, opponents'
                      hole cards are dead cards removed from the deck)
    realized_equity = hero's information-perspective equity (hero's own cards +
                      board + unknown opponent range; opponents' actual hole
                      cards are NEVER used)
    disparity       = realized_equity − raw_equity
    """

    hero_index: int
    villain_index: int
    hero_cards: list[str]
    villain_cards: list[str]
    raw_equity: float
    realized_equity: float
    disparity: float


class EquityResult(BaseModel):
    variant: str
    hands: list[list[str]]
    board: list[str]
    results: list[DirectionalResult] = Field(default_factory=list)
    samples: int
    error: str = ""


class PlayerView(BaseModel):
    player_id: str
    username: str
    display_name: str
    enabled: bool
    notes: str
