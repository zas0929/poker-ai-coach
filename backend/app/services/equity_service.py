from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from hashlib import sha256
from itertools import accumulate
import json
from math import log, sqrt
import random

from app.models.poker import Card, HandState, Rank, Suit
from app.services.hand_evaluator import HandEvaluator
from app.services.range_service import OpponentRange, RangeService


@dataclass(frozen=True)
class EquityEstimate:
    equity: float
    method: str
    samples: int
    sampling_error: float


class EquityService:
    def __init__(self, evaluator: HandEvaluator | None = None):
        self.evaluator = evaluator or HandEvaluator()
        self.range_service = RangeService(self.evaluator)

    def estimate_equity(self, state: HandState, player_id: str = "hero", simulations: int = 1000) -> float:
        return self.estimate(state, player_id, simulations=simulations).equity

    def estimate(
        self, state: HandState, player_id: str = "hero",
        opponent_range: OpponentRange | None = None, simulations: int = 1000,
    ) -> EquityEstimate:
        player = self._get_player(state, player_id)
        if len(player.cards) != 2 or len(state.board) > 5:
            raise ValueError("Equity needs two player cards and at most five board cards.")
        known_cards = [*player.cards, *state.board]
        if len({(c.rank, c.suit) for c in known_cards}) != len(known_cards):
            raise ValueError("Player cards and board must be distinct.")
        if simulations <= 0:
            raise ValueError("Simulation count must be positive.")
        inferred = opponent_range or self.range_service.infer(state, player_id)
        if not inferred.combos:
            raise ValueError("Opponent range has no legal combinations.")
        cumulative = list(accumulate(c.weight for c in inferred.combos))
        total = cumulative[-1]
        if total <= 0 or any(c.weight < 0 for c in inferred.combos):
            raise ValueError("Opponent range weights must be nonnegative with a positive total.")

        # On the river there is no runout to sample: enumerate every weighted hand.
        if len(state.board) == 5:
            hero_score = self._score([*player.cards, *state.board])
            wins = sum(
                combo.weight * self._outcome(hero_score, self._score([*combo.cards, *state.board]))
                for combo in inferred.combos
            )
            return EquityEstimate(round(wins / total, 4), "exact_river", len(inferred.combos), 0.0)

        # Stable samples for identical information states; no hidden opponent cards
        # or deck order enter either the seed or the inferred range.
        payload = {
            "cards": [(c.rank.value, c.suit.value) for c in known_cards],
            "weights": [c.weight for c in inferred.combos],
        }
        seed = int.from_bytes(sha256(json.dumps(payload, sort_keys=True).encode()).digest()[:8], "big")
        rng = random.Random(seed)
        remaining = self._remaining_deck(known_cards)
        wins = 0.0
        for _ in range(simulations):
            index = min(bisect_right(cumulative, rng.random() * total), len(inferred.combos) - 1)
            opponent_cards = inferred.combos[index].cards
            blocked = {(c.rank, c.suit) for c in opponent_cards}
            deck = [c for c in remaining if (c.rank, c.suit) not in blocked]
            runout = [*state.board, *rng.sample(deck, 5 - len(state.board))]
            wins += self._outcome(
                self._score([*player.cards, *runout]), self._score([*opponent_cards, *runout])
            )
        # Hoeffding's 95% bound for bounded [0,1] outcomes; model error excluded.
        error = sqrt(log(40) / (2 * simulations))
        return EquityEstimate(round(wins / simulations, 4), "monte_carlo", simulations, round(error, 4))

    def _score(self, cards: list[Card]) -> tuple:
        strength = self.evaluator.evaluate(cards)
        return strength.rank, strength.kickers

    @staticmethod
    def _outcome(hero_score: tuple, opponent_score: tuple) -> float:
        return 1.0 if hero_score > opponent_score else 0.5 if hero_score == opponent_score else 0.0

    def _remaining_deck(self, excluded_cards: list[Card]) -> list[Card]:
        excluded = {(card.rank, card.suit) for card in excluded_cards}
        return [Card(rank=rank, suit=suit) for rank in Rank for suit in Suit if (rank, suit) not in excluded]

    def _get_player(self, state: HandState, player_id: str):
        for player in state.players:
            if player.id == player_id:
                return player
        raise ValueError(f"Player {player_id} was not found.")
