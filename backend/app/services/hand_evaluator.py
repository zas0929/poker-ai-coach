from __future__ import annotations

from collections import Counter
from itertools import combinations

from app.models.poker import Card, HandStrength, Rank

RANK_VALUES = {
    Rank.TWO: 2,
    Rank.THREE: 3,
    Rank.FOUR: 4,
    Rank.FIVE: 5,
    Rank.SIX: 6,
    Rank.SEVEN: 7,
    Rank.EIGHT: 8,
    Rank.NINE: 9,
    Rank.TEN: 10,
    Rank.JACK: 11,
    Rank.QUEEN: 12,
    Rank.KING: 13,
    Rank.ACE: 14,
}

CATEGORY_NAMES = {
    8: "straight_flush",
    7: "four_of_a_kind",
    6: "full_house",
    5: "flush",
    4: "straight",
    3: "three_of_a_kind",
    2: "two_pair",
    1: "one_pair",
    0: "high_card",
}


class HandEvaluator:
    def evaluate(self, cards: list[Card]) -> HandStrength:
        if len(cards) < 5:
            return self._pre_showdown_strength(cards)

        best_cards: tuple[Card, ...] | None = None
        best_score: tuple[int, list[int]] | None = None

        for combo in combinations(cards, 5):
            score = self._score_five_cards(list(combo))
            if best_score is None or score > best_score:
                best_score = score
                best_cards = combo

        assert best_score is not None
        assert best_cards is not None

        category_rank, kickers = best_score
        return HandStrength(
            category=CATEGORY_NAMES[category_rank],
            rank=category_rank,
            kickers=kickers,
            cards=list(best_cards),
        )

    def compare(self, first: list[Card], second: list[Card]) -> int:
        first_strength = self.evaluate(first)
        second_strength = self.evaluate(second)
        first_score = (first_strength.rank, first_strength.kickers)
        second_score = (second_strength.rank, second_strength.kickers)

        if first_score > second_score:
            return 1
        if first_score < second_score:
            return -1
        return 0

    def _score_five_cards(self, cards: list[Card]) -> tuple[int, list[int]]:
        values = sorted((RANK_VALUES[card.rank] for card in cards), reverse=True)
        counts = Counter(values)
        groups = sorted(counts.items(), key=lambda item: (item[1], item[0]), reverse=True)
        is_flush = len({card.suit for card in cards}) == 1
        straight_high = self._straight_high(values)

        if is_flush and straight_high:
            return 8, [straight_high]

        if groups[0][1] == 4:
            quad = groups[0][0]
            kicker = max(value for value in values if value != quad)
            return 7, [quad, kicker]

        if groups[0][1] == 3 and groups[1][1] == 2:
            return 6, [groups[0][0], groups[1][0]]

        if is_flush:
            return 5, values

        if straight_high:
            return 4, [straight_high]

        if groups[0][1] == 3:
            trips = groups[0][0]
            kickers = sorted((value for value in values if value != trips), reverse=True)
            return 3, [trips, *kickers]

        pairs = sorted((value for value, count in counts.items() if count == 2), reverse=True)
        if len(pairs) == 2:
            kicker = max(value for value in values if value not in pairs)
            return 2, [*pairs, kicker]

        if len(pairs) == 1:
            pair = pairs[0]
            kickers = sorted((value for value in values if value != pair), reverse=True)
            return 1, [pair, *kickers]

        return 0, values

    def _straight_high(self, values: list[int]) -> int | None:
        unique_values = sorted(set(values), reverse=True)
        if {14, 5, 4, 3, 2}.issubset(unique_values):
            return 5

        for index in range(len(unique_values) - 4):
            window = unique_values[index : index + 5]
            if window[0] - window[4] == 4:
                return window[0]

        return None

    def _pre_showdown_strength(self, cards: list[Card]) -> HandStrength:
        values = sorted((RANK_VALUES[card.rank] for card in cards), reverse=True)
        counts = Counter(values)
        pairs = [value for value, count in counts.items() if count == 2]
        category_rank = 1 if pairs else 0

        return HandStrength(
            category=CATEGORY_NAMES[category_rank],
            rank=category_rank,
            kickers=values,
            cards=cards,
        )
