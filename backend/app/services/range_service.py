"""Transparent, uncalibrated per-opponent ranges inferred from public actions.

Weights are relative action likelihoods, not solver frequencies. Blinds alone
leave every legal combination equally likely. Opponent hole cards are never read.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import exp

from app.models.poker import Card, HandState, OpponentRangeSummary, PlayerStatus, Street
from app.services.hand_evaluator import HandEvaluator, RANK_VALUES


@dataclass(frozen=True)
class WeightedCombo:
    cards: tuple[Card, Card]
    weight: float


@dataclass
class OpponentRange:
    combos: list[WeightedCombo]
    summary: OpponentRangeSummary


class RangeService:
    def __init__(self, evaluator: HandEvaluator | None = None):
        self.evaluator = evaluator or HandEvaluator()

    def infer(self, state: HandState, player_id: str = "hero", opponent_id: str | None = None) -> OpponentRange:
        return self._infer(state, player_id, opponent_id)

    def infer_public(self, state: HandState, player_id: str) -> OpponentRange:
        """Full public range for a solver: do not condition on any private hand.

        The actual hero combination is selected from the eventual solution later.
        Feeding it into these ranges would reveal it to the modelled opponents.
        """
        return self._infer(state, None, player_id)

    def _infer(self, state: HandState, player_id: str | None, opponent_id: str | None) -> OpponentRange:
        player = next((p for p in state.players if p.id == player_id), None) if player_id is not None else None
        if player_id is not None and player is None:
            raise ValueError(f"Player {player_id} was not found.")
        opponents = [p for p in state.players if p.id != player_id and p.status != PlayerStatus.FOLDED]
        if opponent_id is None and len(opponents) > 1:
            raise ValueError("Specify an opponent for a multiway range.")
        opponent = next((p for p in opponents if opponent_id is None or p.id == opponent_id), None)
        if opponent is None:
            raise ValueError("No live opponent matches this range request.")
        known = {(c.rank, c.suit) for c in [*(player.cards if player else []), *state.board]}
        from app.models.poker import Rank, Suit
        deck = [Card(rank=r, suit=s) for r in Rank for s in Suit if (r, s) not in known]
        evidence = []
        observations = []
        preflop_raises = 0
        for action in state.history:
            if action.player_id == opponent.id and action.action in {"call", "check", "bet", "raise"}:
                observations.append((action, preflop_raises))
                evidence.append(f"{action.street.value}: {action.action}")
            if action.street == Street.PREFLOP and action.action in {"bet", "raise"}:
                preflop_raises += 1

        combos = []
        classes: dict[str, float] = {}
        # Only board cards already dealt on each action's street inform that action.
        board_sizes = {Street.FLOP: 3, Street.TURN: 4, Street.RIVER: 5}
        for cards in combinations(deck, 2):
            weight = 1.0
            for action, previous_raises in observations:
                if action.street == Street.PREFLOP:
                    strength = self.preflop_strength(cards)
                    if action.action in {"bet", "raise"}:
                        button = opponent.position in {"small_blind_button", "button", "cutoff"}
                        threshold = min(0.88, (0.38 if button else 0.48) + 0.16 * previous_raises)
                        weight *= self._continue_weight(strength, threshold)
                    elif action.action == "call":
                        threshold = min(0.8, 0.18 + 0.14 * previous_raises)
                        weight *= self._continue_weight(strength, threshold)
                    else:
                        weight *= 1.0 - 0.7 * self._continue_weight(strength, 0.75)
                elif action.street in board_sizes:
                    board = state.board[:board_sizes[action.street]]
                    if len(board) < board_sizes[action.street]:
                        raise ValueError("Action history refers to board cards not yet dealt.")
                    strength = self._postflop_strength(cards, board)
                    if action.action in {"bet", "raise"}:
                        # Keep weak hands in the range as possible bluffs.
                        weight *= 0.12 + 0.88 * self._continue_weight(
                            strength, 0.6 if action.action == "raise" else 0.48
                        )
                    elif action.action == "call":
                        weight *= self._continue_weight(strength, 0.35)
                    else:
                        # Checking is weak evidence: strong hands can trap.
                        weight *= 1.0 - 0.35 * strength
            combos.append(WeightedCombo(cards=cards, weight=weight))
            notation = self.notation(cards)
            classes[notation] = classes.get(notation, 0.0) + weight

        total = sum(c.weight for c in combos)
        effective = total * total / sum(c.weight * c.weight for c in combos)
        summary = OpponentRangeSummary(
            player_id=opponent.id,
            position=opponent.position,
            model="action_weighted" if evidence else "uniform",
            legal_combos=len(combos),
            effective_combos=round(effective, 1),
            top_hands=sorted(classes, key=classes.get, reverse=True)[:8] if evidence else [],
            evidence=evidence,
            description=(
                "Heuristic range weighted by position and observed actions; not a GTO solution."
                if evidence else "No voluntary actions observed: all legal hands have equal weight."
            ),
        )
        return OpponentRange(combos=combos, summary=summary)

    @staticmethod
    def _continue_weight(strength: float, threshold: float) -> float:
        return 0.02 + 0.98 / (1.0 + exp(-12.0 * (strength - threshold)))

    @staticmethod
    def preflop_strength(cards: tuple[Card, Card]) -> float:
        high, low = sorted((RANK_VALUES[c.rank] for c in cards), reverse=True)
        if high == low:
            return 0.48 + (high - 2) / 12 * 0.5
        suited = cards[0].suit == cards[1].suit
        gap = high - low
        return min(0.95, 0.07 + 0.35 * (high - 2) / 12 + 0.22 * (low - 2) / 12
                   + 0.08 * suited + (0.08 if gap == 1 else 0.04 if gap == 2 else 0)
                   + (0.05 if high == 14 else 0))

    def _postflop_strength(self, cards: tuple[Card, Card], board: list[Card]) -> float:
        rank, kickers = self.evaluator.score([*cards, *board])
        value = [0.12, 0.48, 0.68, 0.8, 0.88, 0.92, 0.96, 0.98, 1.0][rank]
        if len(board) == 5:
            if (rank, kickers) == self.evaluator.score(board):
                return 0.15
        if rank == 1 and cards[0].rank != cards[1].rank:
            if kickers[0] not in {RANK_VALUES[c.rank] for c in cards}:
                value = 0.2  # A pair on the board alone is not a personal made pair.
        if rank == 0:
            value += 0.1 * max(RANK_VALUES[c.rank] for c in cards) / 14
        if len(board) < 5:
            all_cards = [*cards, *board]
            flush_draw = any(
                sum(c.suit == hole.suit for c in all_cards) == 4 for hole in cards
            )
            values = {RANK_VALUES[c.rank] for c in all_cards}
            if 14 in values:
                values.add(1)
            hole_values = {RANK_VALUES[c.rank] for c in cards}
            if 14 in hole_values:
                hole_values.add(1)
            straight_draw = any(
                len(values & set(range(start, start + 5))) == 4
                and bool(hole_values & set(range(start, start + 5)))
                for start in range(1, 11)
            )
            value += 0.18 * flush_draw + 0.12 * straight_draw
        return min(value, 1.0)

    @staticmethod
    def notation(cards: tuple[Card, Card]) -> str:
        high, low = sorted(cards, key=lambda c: RANK_VALUES[c.rank], reverse=True)
        return high.rank.value + low.rank.value + (
            "" if high.rank == low.rank else "s" if high.suit == low.suit else "o"
        )
