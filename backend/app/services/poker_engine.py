from __future__ import annotations

import random
import uuid

from app.models.poker import (
    ActionType,
    Card,
    HandAction,
    HandResult,
    HandState,
    Player,
    PlayerHandResult,
    PlayerStatus,
    Rank,
    Street,
    Suit,
)
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


class PokerEngine:
    def __init__(self):
        self.deck: list[Card] = self._create_deck()
        self.evaluator = HandEvaluator()

    def _create_deck(self) -> list[Card]:
        return [Card(rank=rank, suit=suit) for rank in RANKS for suit in SUITS]

    def _shuffle(self) -> None:
        random.shuffle(self.deck)

    def _draw(self, count: int) -> list[Card]:
        return [self.deck.pop() for _ in range(count)]

    def start_hand(self) -> HandState:
        self.deck = self._create_deck()
        self._shuffle()

        small_blind = 5
        big_blind = 10

        hero = Player(
            id="hero",
            name="You",
            stack=1000 - small_blind,
            position="small_blind_button",
            cards=self._draw(2),
            current_bet=small_blind,
        )
        villain = Player(
            id="villain",
            name="AI Opponent",
            stack=1000 - big_blind,
            position="big_blind",
            cards=self._draw(2),
            current_bet=big_blind,
        )

        return HandState(
            hand_id=str(uuid.uuid4()),
            street=Street.PREFLOP,
            pot=small_blind + big_blind,
            small_blind=small_blind,
            big_blind=big_blind,
            board=[],
            players=[hero, villain],
            current_player_id="hero",
            dealer_player_id="hero",
            history=[
                HandAction(player_id="hero", action="small_blind", amount=small_blind, street=Street.PREFLOP),
                HandAction(player_id="villain", action="big_blind", amount=big_blind, street=Street.PREFLOP),
            ],
            notes=["New heads-up hand started."],
        )

    def deal_flop(self, state: HandState) -> HandState:
        self._ensure_street(state, Street.PREFLOP)
        self._ensure_round_closed(state)
        self._reset_street_bets(state)
        state.board.extend(self._draw(3))
        state.street = Street.FLOP
        state.current_player_id = "villain"
        state.notes.append("Flop dealt.")
        return state

    def deal_turn(self, state: HandState) -> HandState:
        self._ensure_street(state, Street.FLOP)
        self._ensure_round_closed(state)
        self._reset_street_bets(state)
        state.board.extend(self._draw(1))
        state.street = Street.TURN
        state.current_player_id = "villain"
        state.notes.append("Turn dealt.")
        return state

    def deal_river(self, state: HandState) -> HandState:
        self._ensure_street(state, Street.TURN)
        self._ensure_round_closed(state)
        self._reset_street_bets(state)
        state.board.extend(self._draw(1))
        state.street = Street.RIVER
        state.current_player_id = "villain"
        state.notes.append("River dealt.")
        return state

    def advance(self, state: HandState) -> HandState:
        self._ensure_round_closed(state)
        self._ensure_hand_not_folded(state)

        if state.street == Street.PREFLOP:
            return self.deal_flop(state)
        if state.street == Street.FLOP:
            return self.deal_turn(state)
        if state.street == Street.TURN:
            return self.deal_river(state)
        if state.street == Street.RIVER:
            self._reset_street_bets(state)
            state.street = Street.SHOWDOWN
            state.current_player_id = None
            self._resolve_showdown(state)
            return state

        raise ValueError("Hand is already at showdown.")

    def apply_action(
        self,
        state: HandState,
        player_id: str,
        action: ActionType,
        amount: int | None = None,
    ) -> HandState:
        if state.current_player_id != player_id:
            raise ValueError(f"It is {state.current_player_id}'s turn, not {player_id}'s.")

        player = self._get_player(state, player_id)
        if player.status != PlayerStatus.ACTIVE:
            raise ValueError(f"Player {player_id} is not active.")

        if action == ActionType.FOLD:
            player.status = PlayerStatus.FOLDED
            state.history.append(HandAction(player_id=player_id, action=action.value, street=state.street))
            state.current_player_id = None
            self._resolve_fold(state, folded_player_id=player_id)
            return state

        if action == ActionType.CHECK:
            if self._call_amount(state, player) != 0:
                raise ValueError("Cannot check while facing a bet.")
            closes_round = self._previous_action_was_check(state, player_id)
            state.history.append(HandAction(player_id=player_id, action=action.value, street=state.street))
            state.current_player_id = None if closes_round else self._other_active_player_id(state, player_id)
            return state

        if action == ActionType.CALL:
            call_amount = self._call_amount(state, player)
            if call_amount <= 0:
                raise ValueError("Cannot call when there is no bet to call.")
            committed = self._commit_chips(state, player, call_amount)
            state.history.append(HandAction(player_id=player_id, action=action.value, amount=committed, street=state.street))
            state.current_player_id = None
            return state

        if action == ActionType.BET:
            if self._highest_bet(state) != 0:
                raise ValueError("Use raise when a bet already exists on this street.")
            bet_amount = self._require_positive_amount(amount)
            committed = self._commit_chips(state, player, bet_amount)
            state.history.append(HandAction(player_id=player_id, action=action.value, amount=committed, street=state.street))
            state.current_player_id = self._other_active_player_id(state, player_id)
            return state

        if action == ActionType.RAISE:
            target_bet = self._require_positive_amount(amount)
            highest_bet = self._highest_bet(state)
            if target_bet <= highest_bet:
                raise ValueError("Raise amount must be greater than the current highest bet.")
            committed = self._commit_chips(state, player, target_bet - player.current_bet)
            state.history.append(HandAction(player_id=player_id, action=action.value, amount=committed, street=state.street))
            state.current_player_id = self._other_active_player_id(state, player_id)
            return state

        raise ValueError(f"Unsupported action: {action}.")

    def _ensure_street(self, state: HandState, expected: Street) -> None:
        if state.street != expected:
            raise ValueError(f"Expected {expected} street, got {state.street}.")

    def _ensure_round_closed(self, state: HandState) -> None:
        if state.current_player_id is not None:
            raise ValueError("Cannot advance while betting action is still open.")

    def _ensure_hand_not_folded(self, state: HandState) -> None:
        active_players = [player for player in state.players if player.status != PlayerStatus.FOLDED]
        if len(active_players) < 2:
            raise ValueError("Hand is already over because a player folded.")

    def _reset_street_bets(self, state: HandState) -> None:
        for player in state.players:
            player.current_bet = 0

    def _get_player(self, state: HandState, player_id: str) -> Player:
        for player in state.players:
            if player.id == player_id:
                return player
        raise ValueError(f"Player {player_id} was not found.")

    def _highest_bet(self, state: HandState) -> int:
        return max(player.current_bet for player in state.players)

    def _call_amount(self, state: HandState, player: Player) -> int:
        return max(self._highest_bet(state) - player.current_bet, 0)

    def _commit_chips(self, state: HandState, player: Player, amount: int) -> int:
        committed = min(amount, player.stack)
        player.stack -= committed
        player.current_bet += committed
        state.pot += committed

        if player.stack == 0:
            player.status = PlayerStatus.ALL_IN

        return committed

    def _other_active_player_id(self, state: HandState, player_id: str) -> str | None:
        for player in state.players:
            if player.id != player_id and player.status == PlayerStatus.ACTIVE:
                return player.id
        return None

    def _previous_action_was_check(self, state: HandState, player_id: str) -> bool:
        for action in reversed(state.history):
            if action.street != state.street:
                continue
            return action.player_id != player_id and action.action == ActionType.CHECK.value
        return False

    def _require_positive_amount(self, amount: int | None) -> int:
        if amount is None or amount <= 0:
            raise ValueError("Amount must be a positive integer.")
        return amount

    def _resolve_fold(self, state: HandState, folded_player_id: str) -> None:
        winner = next(player for player in state.players if player.id != folded_player_id)
        pot_awarded = state.pot
        winner.stack += pot_awarded
        state.pot = 0
        state.result = HandResult(
            reason="fold",
            winners=[winner.id],
            pot_awarded=pot_awarded,
            player_results=[
                PlayerHandResult(
                    player_id=player.id,
                    outcome="folded" if player.id == folded_player_id else "win",
                    amount_won=pot_awarded if player.id == winner.id else 0,
                )
                for player in state.players
            ],
        )
        state.notes.append(f"{winner.name} wins {pot_awarded} after fold.")

    def _resolve_showdown(self, state: HandState) -> None:
        pot_awarded = state.pot
        active_players = [player for player in state.players if player.status != PlayerStatus.FOLDED]
        strengths = {
            player.id: self.evaluator.evaluate([*player.cards, *state.board])
            for player in active_players
        }
        best_player = active_players[0]
        tied_winners = [best_player]

        for player in active_players[1:]:
            comparison = self.evaluator.compare(
                [*player.cards, *state.board],
                [*best_player.cards, *state.board],
            )
            if comparison > 0:
                best_player = player
                tied_winners = [player]
            elif comparison == 0:
                tied_winners.append(player)

        share = pot_awarded // len(tied_winners)
        remainder = pot_awarded % len(tied_winners)
        winner_ids = [player.id for player in tied_winners]
        player_results: list[PlayerHandResult] = []

        for player in state.players:
            amount_won = 0
            outcome = "lose"

            if player.id in winner_ids:
                amount_won = share + (remainder if player.id == winner_ids[0] else 0)
                player.stack += amount_won
                outcome = "tie" if len(winner_ids) > 1 else "win"

            player_results.append(
                PlayerHandResult(
                    player_id=player.id,
                    outcome=outcome,
                    amount_won=amount_won,
                    hand_strength=strengths.get(player.id),
                )
            )

        state.pot = 0
        state.result = HandResult(
            reason="showdown",
            winners=winner_ids,
            pot_awarded=pot_awarded,
            player_results=player_results,
        )
        state.notes.append(f"Showdown reached. Winner: {', '.join(winner_ids)}.")
