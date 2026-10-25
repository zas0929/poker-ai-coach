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

export interface PreflopProfile {
  notation: string;
  category: string;
  score: number;
  tags: string[];
}

export interface DrawProfile {
  outs: number;
  draws: string[];
  overcards: number;
}

export interface PlayerHandResult {
  player_id: string;
  outcome: string;
  amount_won: number;
  hand_strength?: HandStrength | null;
}

export interface PotResult {
  amount: number;
  eligible_player_ids: string[];
  winners: string[];
  awards: Record<string, number>;
}

export interface HandResult {
  reason: string;
  winners: string[];
  pot_awarded: number;
  player_results: PlayerHandResult[];
  pots?: PotResult[];
}

export interface BettingOptions {
  player_id?: string | null;
  legal_actions: ActionType[];
  call_amount: number;
  min_bet?: number | null;
  min_raise_to?: number | null;
  max_raise_to?: number | null;
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
  betting?: BettingOptions | null;
  last_full_raise?: number;
  acted_at_bet?: Record<string, number>;
  contributions?: Record<string, number>;
}

export interface OpponentRangeSummary {
  player_id: string;
  position: string;
  model: 'uniform' | 'action_weighted';
  legal_combos: number;
  effective_combos: number;
  top_hands: string[];
  evidence: string[];
  description: string;
}

export interface HandAnalysis {
  hand_id: string;
  street: Street;
  pot: number;
  player_id: string;
  call_amount: number;
  required_equity: number;
  equity: number;
  opponent_range?: OpponentRangeSummary | null;
  opponent_ranges?: OpponentRangeSummary[];
  opponent_count?: number;
  call_ev_available?: boolean;
  equity_method?: 'monte_carlo' | 'exact_river' | 'monte_carlo_multiway';
  equity_samples?: number;
  equity_sampling_error?: number;
  ev_call: number;
  recommended_action: string;
  recommended_amount?: number | null;
  hand_strength: HandStrength;
  preflop_profile: PreflopProfile;
  draw_profile: DrawProfile;
  rule_advice?: { scenario?: string; opener_position?: string | null; effective_stack_bb?: number; stack_band?: string; range_status?: string; range_hands?: string[]; range_covered?: boolean; version: string; action: string; hand_label: string; board_texture: string[]; purpose: string; reason: string; live_opponents: number; close_price: boolean; limitations: string } | null;
  coach_summary: string;
  confidence: number;
  risk_level: string;
  key_factors: string[];
  notes: string[];
}

export interface ActionReview {
  hand_id: string;
  street: Street;
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
