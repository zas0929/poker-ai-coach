from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from hashlib import sha256
from itertools import accumulate
import json
from math import isfinite, log, sqrt
import random

from app.models.poker import Card, HandState, PlayerStatus, Rank, Suit
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
        opponent_ranges: list[OpponentRange] | None = None,
    ) -> EquityEstimate:
        player = self._get_player(state, player_id)
        if len(player.cards) != 2 or len(state.board) > 5:
            raise ValueError("Equity needs two player cards and at most five board cards.")
        known_cards = [*player.cards, *state.board]
        if len({(c.rank, c.suit) for c in known_cards}) != len(known_cards):
            raise ValueError("Player cards and board must be distinct.")
        if type(simulations) is not int or simulations <= 0:
            raise ValueError("Simulation count must be positive.")
        live_opponents = [p for p in state.players if p.id != player_id and p.status != PlayerStatus.FOLDED]
        if len(live_opponents) > 1:
            ranges = opponent_ranges or [self.range_service.infer(state, player_id, p.id) for p in live_opponents]
            return self._estimate_multiway(state, player_id, ranges, simulations)
        inferred = opponent_range or self.range_service.infer(state, player_id)
        self._validate_range(inferred, known_cards)
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

    def _estimate_multiway(self, state: HandState, player_id: str, ranges: list[OpponentRange], simulations: int) -> EquityEstimate:
        player = self._get_player(state, player_id)
        if len(ranges) != sum(p.id != player_id and p.status != PlayerStatus.FOLDED for p in state.players):
            raise ValueError("Provide one range per live opponent.")
        for inferred in ranges:
            self._validate_range(inferred, [*player.cards, *state.board])
        cumulative = [list(accumulate(c.weight for c in r.combos)) for r in ranges]
        if any(not c or c[-1] <= 0 for c in cumulative):
            raise ValueError("All opponent ranges need positive legal weight.")
        known = [*player.cards, *state.board]
        payload = {"cards": [(c.rank.value, c.suit.value) for c in known],
                   "ranges": [[([(c.rank.value, c.suit.value) for c in combo.cards], combo.weight)
                               for combo in r.combos] for r in ranges]}
        rng = random.Random(int.from_bytes(sha256(json.dumps(payload).encode()).digest()[:8], 'big'))
        remaining = self._remaining_deck(known)
        known_keys = {(c.rank, c.suit) for c in known}
        wins = 0.0
        for _ in range(simulations):
            # Reject the entire lineup on collisions: sequentially conditioning each
            # hand would bias the product-of-ranges joint distribution.
            for attempt in range(10000):
                hands = [r.combos[min(bisect_right(c, rng.random() * c[-1]), len(r.combos)-1)].cards
                         for r, c in zip(ranges, cumulative)]
                keys = [(card.rank, card.suit) for hand in hands for card in hand]
                if len(keys) == len(set(keys)) and not known_keys.intersection(keys):
                    break
            else:
                raise ValueError("Opponent ranges have no reasonably sampleable disjoint lineup.")
            blocked = set(keys)
            deck = [c for c in remaining if (c.rank, c.suit) not in blocked]
            board = [*state.board, *rng.sample(deck, 5 - len(state.board))]
            scores = [self._score([*player.cards, *board]), *[self._score([*hand, *board]) for hand in hands]]
            best = max(scores)
            if scores[0] == best:
                wins += 1 / scores.count(best)
        return EquityEstimate(round(wins / simulations, 4), 'monte_carlo_multiway', simulations,
                              round(sqrt(log(40) / (2 * simulations)), 4))

    @staticmethod
    def _validate_range(inferred: OpponentRange, known_cards: list[Card]) -> None:
        """Validate supplied ranges as strictly as the internally inferred ones."""
        known = {(c.rank, c.suit) for c in known_cards}
        seen = set()
        total = 0.0
        for combo in inferred.combos:
            keys = frozenset((c.rank, c.suit) for c in combo.cards)
            if len(combo.cards) != 2 or len(keys) != 2 or keys.intersection(known):
                raise ValueError("Opponent range contains duplicate or blocked cards.")
            if keys in seen:
                raise ValueError("Opponent range contains duplicate combinations.")
            seen.add(keys)
            if not isfinite(combo.weight) or combo.weight < 0:
                raise ValueError("Opponent range weights must be finite and nonnegative.")
            total += combo.weight
        if not isfinite(total) or total <= 0:
            raise ValueError("Opponent range needs a positive finite total weight.")

    def _score(self, cards: list[Card]) -> tuple:
        return self.evaluator.score(cards)

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
