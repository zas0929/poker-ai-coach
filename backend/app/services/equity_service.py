from __future__ import annotations

import random

from app.models.poker import Card, HandState, Rank, Suit
from app.services.hand_evaluator import HandEvaluator

RANKS = [
    Rank.ACE,
    Rank.KING,
    Rank.QUEEN,
    Rank.JACK,
    Rank.TEN,
    Rank.NINE,
    Rank.EIGHT,
    Rank.SEVEN,
    Rank.SIX,
    Rank.FIVE,
    Rank.FOUR,
    Rank.THREE,
    Rank.TWO,
]

SUITS = [Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS]


class EquityService:
    def __init__(self, evaluator: HandEvaluator | None = None):
        self.evaluator = evaluator or HandEvaluator()

    def estimate_equity(self, state: HandState, player_id: str = "hero", simulations: int = 1000) -> float:
        player = self._get_player(state, player_id)
        known_cards = [*player.cards, *state.board]
        wins = 0.0

        for _ in range(simulations):
            deck = self._remaining_deck(known_cards)
            random.shuffle(deck)

            opponent_cards = [deck.pop(), deck.pop()]
            runout = [*state.board]
            while len(runout) < 5:
                runout.append(deck.pop())

            result = self.evaluator.compare([*player.cards, *runout], [*opponent_cards, *runout])
            if result > 0:
                wins += 1
            elif result == 0:
                wins += 0.5

        return round(wins / simulations, 4)

    def _remaining_deck(self, excluded_cards: list[Card]) -> list[Card]:
        excluded = {(card.rank, card.suit) for card in excluded_cards}
        return [
            Card(rank=rank, suit=suit)
            for rank in RANKS
            for suit in SUITS
            if (rank, suit) not in excluded
        ]

    def _get_player(self, state: HandState, player_id: str):
        for player in state.players:
            if player.id == player_id:
                return player
        raise ValueError(f"Player {player_id} was not found.")
