export type Rank = 'A' | 'K' | 'Q' | 'J' | 'T' | '9' | '8' | '7' | '6' | '5' | '4' | '3' | '2';

export type Suit = 'spades' | 'hearts' | 'diamonds' | 'clubs';

export type Street = 'preflop' | 'flop' | 'turn' | 'river' | 'showdown';

export type PlayerStatus = 'active' | 'folded' | 'all_in';

export type ActionType = 'fold' | 'check' | 'call' | 'bet' | 'raise';

export interface Card {
  rank: Rank;
  suit: Suit;
}

export interface Player {
  id: string;
  name: string;
  stack: number;
  position: string;
  cards: Card[];
  status: PlayerStatus;
  current_bet: number;
}

export interface HandAction {
  player_id: string;
  action: string;
  amount?: number | null;
  street: Street;
}

export interface HandStrength {
  category: string;
  rank: number;
  kickers: number[];
  cards: Card[];
}

export interface PlayerHandResult {
  player_id: string;
  outcome: string;
  amount_won: number;
  hand_strength?: HandStrength | null;
}

export interface HandResult {
  reason: string;
  winners: string[];
  pot_awarded: number;
  player_results: PlayerHandResult[];
}

export interface HandState {
  hand_id: string;
  street: Street;
  pot: number;
  small_blind: number;
  big_blind: number;
  board: Card[];
  players: Player[];
  current_player_id?: string | null;
  dealer_player_id: string;
  history: HandAction[];
  notes: string[];
  result?: HandResult | null;
}

export interface HandAnalysis {
  hand_id: string;
  street: Street;
  pot: number;
  player_id: string;
  call_amount: number;
  required_equity: number;
  equity: number;
  ev_call: number;
  recommended_action: string;
  hand_strength: HandStrength;
  coach_summary: string;
  confidence: number;
  risk_level: string;
  key_factors: string[];
  notes: string[];
}

export interface ActionReview {
  chosen_action: ActionType;
  recommended_action: string;
  verdict: 'optimal' | 'acceptable' | 'reconsider';
  summary: string;
}

export interface PlayerActionRequest {
  player_id: string;
  action: ActionType;
  amount?: number;
}
