from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Rank(str, Enum):
    ACE = "A"
    KING = "K"
    QUEEN = "Q"
    JACK = "J"
    TEN = "T"
    NINE = "9"
    EIGHT = "8"
    SEVEN = "7"
    SIX = "6"
    FIVE = "5"
    FOUR = "4"
    THREE = "3"
    TWO = "2"


class Suit(str, Enum):
    SPADES = "spades"
    HEARTS = "hearts"
    DIAMONDS = "diamonds"
    CLUBS = "clubs"


class Street(str, Enum):
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"


class PlayerStatus(str, Enum):
    ACTIVE = "active"
    FOLDED = "folded"
    ALL_IN = "all_in"


class ActionType(str, Enum):
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"


class Card(BaseModel):
    rank: Rank
    suit: Suit


class Player(BaseModel):
    id: str
    name: str
    stack: int
    position: str
    cards: list[Card] = Field(default_factory=list)
    status: PlayerStatus = PlayerStatus.ACTIVE
    current_bet: int = 0


class HandAction(BaseModel):
    player_id: str
    action: str
    amount: Optional[int] = None
    street: Street


class PlayerActionRequest(BaseModel):
    player_id: str = "hero"
    action: ActionType
    amount: Optional[int] = None


class HandStrength(BaseModel):
    category: str
    rank: int
    kickers: list[int]
    cards: list[Card]


class PlayerHandResult(BaseModel):
    player_id: str
    outcome: str
    amount_won: int = 0
    hand_strength: Optional[HandStrength] = None


class HandResult(BaseModel):
    reason: str
    winners: list[str] = Field(default_factory=list)
    pot_awarded: int
    player_results: list[PlayerHandResult] = Field(default_factory=list)


class HandState(BaseModel):
    hand_id: str
    street: Street
    pot: int
    small_blind: int
    big_blind: int
    board: list[Card] = Field(default_factory=list)
    players: list[Player]
    current_player_id: Optional[str] = None
    dealer_player_id: str
    history: list[HandAction] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    result: Optional[HandResult] = None


class PlayerAnalysis(BaseModel):
    player_id: str
    hand_strength: HandStrength
    equity: float


class HandAnalysis(BaseModel):
    hand_id: str
    street: Street
    pot: int
    player_id: str
    call_amount: int
    required_equity: float
    equity: float
    ev_call: float
    recommended_action: str
    hand_strength: HandStrength
    notes: list[str] = Field(default_factory=list)
