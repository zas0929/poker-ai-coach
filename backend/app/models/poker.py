from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, PrivateAttr, StrictInt


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
    amount: Optional[StrictInt] = None


class HandStrength(BaseModel):
    category: str
    rank: int
    kickers: list[int]
    cards: list[Card]


class PreflopProfile(BaseModel):
    notation: str
    category: str
    score: int
    tags: list[str] = Field(default_factory=list)


class DrawProfile(BaseModel):
    outs: int = 0
    draws: list[str] = Field(default_factory=list)
    overcards: int = 0


class PlayerHandResult(BaseModel):
    player_id: str
    outcome: str
    amount_won: int = 0
    hand_strength: Optional[HandStrength] = None


class PotResult(BaseModel):
    amount: int
    eligible_player_ids: list[str]
    winners: list[str]
    awards: dict[str, int]


class HandResult(BaseModel):
    reason: str
    winners: list[str] = Field(default_factory=list)
    pot_awarded: int
    player_results: list[PlayerHandResult] = Field(default_factory=list)
    pots: list[PotResult] = Field(default_factory=list)


class BettingOptions(BaseModel):
    player_id: Optional[str] = None
    legal_actions: list[ActionType] = Field(default_factory=list)
    call_amount: int = 0
    min_bet: Optional[int] = None
    min_raise_to: Optional[int] = None
    max_raise_to: Optional[int] = None


class HandState(BaseModel):
    _deck: list[Card] = PrivateAttr(default_factory=list)
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
    last_full_raise: int = 0
    acted_at_bet: dict[str, int] = Field(default_factory=dict)
    betting: Optional[BettingOptions] = None
    contributions: dict[str, int] = Field(default_factory=dict)


class PlayerAnalysis(BaseModel):
    player_id: str
    hand_strength: HandStrength
    equity: float


class OpponentRangeSummary(BaseModel):
    player_id: str
    position: str
    model: str
    legal_combos: int
    effective_combos: float
    top_hands: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    description: str


class HandAnalysis(BaseModel):
    rule_advice: Optional[dict] = None
    hand_id: str
    street: Street
    pot: int
    player_id: str
    call_amount: int
    required_equity: float
    equity: float
    opponent_range: Optional[OpponentRangeSummary] = None
    opponent_ranges: list[OpponentRangeSummary] = Field(default_factory=list)
    opponent_count: int = 1
    call_ev_available: bool = True
    equity_method: str = "monte_carlo"
    equity_samples: int = 0
    equity_sampling_error: float = 0.0
    ev_call: float
    recommended_action: str
    recommended_amount: Optional[int] = None
    hand_strength: HandStrength
    preflop_profile: PreflopProfile
    draw_profile: DrawProfile
    coach_summary: str
    confidence: float
    risk_level: str
    key_factors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
