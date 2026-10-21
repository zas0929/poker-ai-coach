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
from app.services.betting_rules import betting_options
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

    def start_hand(self, previous_state: HandState | None = None) -> HandState:
        if previous_state is not None and previous_state.result is None:
            raise ValueError("Finish the current hand before starting another.")
        self.deck = self._create_deck()
        self._shuffle()

        small_blind = 5
        big_blind = 10
        stacks = self._starting_stacks(previous_state)
        dealer_player_id = self._next_dealer(previous_state)
        big_blind_player_id = "villain" if dealer_player_id == "hero" else "hero"

        hero_position = "small_blind_button" if dealer_player_id == "hero" else "big_blind"
        villain_position = "small_blind_button" if dealer_player_id == "villain" else "big_blind"
        hero_blind = small_blind if dealer_player_id == "hero" else big_blind
        villain_blind = small_blind if dealer_player_id == "villain" else big_blind

        hero = Player(
            id="hero",
            name="You",
            stack=stacks["hero"] - hero_blind,
            position=hero_position,
            cards=self._draw(2),
            current_bet=hero_blind,
        )
        villain = Player(
            id="villain",
            name="AI Opponent",
            stack=stacks["villain"] - villain_blind,
            position=villain_position,
            cards=self._draw(2),
            current_bet=villain_blind,
        )

        state = HandState(
            hand_id=str(uuid.uuid4()),
            street=Street.PREFLOP,
            pot=small_blind + big_blind,
            last_full_raise=big_blind,
            small_blind=small_blind,
            big_blind=big_blind,
            board=[],
            players=[hero, villain],
            current_player_id=dealer_player_id,
            dealer_player_id=dealer_player_id,
            history=[
                HandAction(player_id=dealer_player_id, action="small_blind", amount=small_blind, street=Street.PREFLOP),
                HandAction(player_id=big_blind_player_id, action="big_blind", amount=big_blind, street=Street.PREFLOP),
            ],
            notes=[f"New heads-up hand started. Button: {dealer_player_id}."],
        )
        return self._refresh_betting(state)

    def deal_flop(self, state: HandState) -> HandState:
        self._ensure_open_hand(state)
        self._ensure_street(state, Street.PREFLOP)
        self._ensure_round_closed(state)
        self._reset_street_bets(state)
        state.board.extend(self._draw(3))
        state.street = Street.FLOP
        state.current_player_id = self._first_postflop_player(state)
        state.notes.append("Flop dealt.")
        return self._refresh_betting(state)

    def deal_turn(self, state: HandState) -> HandState:
        self._ensure_open_hand(state)
        self._ensure_street(state, Street.FLOP)
        self._ensure_round_closed(state)
        self._reset_street_bets(state)
        state.board.extend(self._draw(1))
        state.street = Street.TURN
        state.current_player_id = self._first_postflop_player(state)
        state.notes.append("Turn dealt.")
        return self._refresh_betting(state)

    def deal_river(self, state: HandState) -> HandState:
        self._ensure_open_hand(state)
        self._ensure_street(state, Street.TURN)
        self._ensure_round_closed(state)
        self._reset_street_bets(state)
        state.board.extend(self._draw(1))
        state.street = Street.RIVER
        state.current_player_id = self._first_postflop_player(state)
        state.notes.append("River dealt.")
        return self._refresh_betting(state)

    def advance(self, state: HandState) -> HandState:
        self._ensure_open_hand(state)
        self._ensure_round_closed(state)
        self._resolve_all_in_showdown_if_closed(state)
        if state.result is not None:
            return self._refresh_betting(state)
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
            return self._refresh_betting(state)

        raise ValueError("Hand is already at showdown.")

    def settle_all_in_if_ready(self, state: HandState) -> HandState:
        self._resolve_all_in_showdown_if_closed(state)
        return self._refresh_betting(state)

    def apply_action(
        self,
        state: HandState,
        player_id: str,
        action: ActionType,
        amount: int | None = None,
    ) -> HandState:
        self._ensure_open_hand(state)
        if state.current_player_id != player_id:
            raise ValueError(f"It is {state.current_player_id}'s turn, not {player_id}'s.")
        player = self._get_player(state, player_id)
        options = betting_options(state, player_id)
        if action not in options.legal_actions:
            raise ValueError(f"Action {action.value} is not legal in the current state.")

        # Validate the entire request before mutating chips, history or turn order.
        if action in {ActionType.BET, ActionType.RAISE}:
            target = self._require_positive_amount(amount)
            minimum = options.min_bet if action == ActionType.BET else options.min_raise_to
            maximum = options.max_raise_to
            if minimum is None or maximum is None or not minimum <= target <= maximum:
                raise ValueError(f"Amount must be between {minimum} and {maximum}.")

        if action == ActionType.FOLD:
            player.status = PlayerStatus.FOLDED
            state.history.append(HandAction(player_id=player_id, action=action.value, street=state.street))
            state.current_player_id = None
            self._return_uncalled_bet(state)
            self._resolve_fold(state, folded_player_id=player_id)
            self._reset_street_bets(state)
            return self._refresh_betting(state)

        if action in {ActionType.CHECK, ActionType.CALL}:
            committed = self._commit_chips(state, player, options.call_amount) if action == ActionType.CALL else None
            state.acted_at_bet[player_id] = self._highest_bet(state)
            state.history.append(HandAction(player_id=player_id, action=action.value, amount=committed, street=state.street))
            closes_round = self._passive_action_closes_round(state)
            state.current_player_id = None if closes_round else self._other_active_player_id(state, player_id)
            self._resolve_all_in_showdown_if_closed(state)
            return self._refresh_betting(state)

        if action in {ActionType.BET, ActionType.RAISE}:
            highest = self._highest_bet(state)
            increment = target - highest
            if increment >= max(state.big_blind, state.last_full_raise):
                state.last_full_raise = increment
            committed = self._commit_chips(state, player, target - player.current_bet)
            state.acted_at_bet[player_id] = target
            state.history.append(HandAction(player_id=player_id, action=action.value, amount=committed, street=state.street))
            state.current_player_id = self._other_active_player_id(state, player_id)
            self._resolve_all_in_showdown_if_closed(state)
            return self._refresh_betting(state)

        raise ValueError(f"Unsupported action: {action}.")

    def _refresh_betting(self, state: HandState) -> HandState:
        state.betting = betting_options(state)
        return state

    def _ensure_open_hand(self, state: HandState) -> None:
        if len(state.players) != 2:
            raise ValueError("This engine currently supports heads-up hands only.")
        if state.result is not None or state.street == Street.SHOWDOWN:
            raise ValueError("Hand is already finished.")

    def _first_postflop_player(self, state: HandState) -> str | None:
        return next((p.id for p in state.players
                     if p.id != state.dealer_player_id and p.status == PlayerStatus.ACTIVE), None)

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
        state.last_full_raise = state.big_blind
        state.acted_at_bet.clear()
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
        if type(amount) is not int or amount <= 0:
            raise ValueError("Chip commitment must be a positive integer.")
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

    def _passive_action_closes_round(self, state: HandState) -> bool:
        highest_bet = self._highest_bet(state)
        players_who_can_act = [
            player
            for player in state.players
            if player.status == PlayerStatus.ACTIVE
        ]
        if any(player.current_bet != highest_bet for player in players_who_can_act):
            return False

        voluntary_actions = [
            action
            for action in state.history
            if action.street == state.street and action.action not in {"small_blind", "big_blind"}
        ]
        acted_player_ids = {action.player_id for action in voluntary_actions}
        return all(player.id in acted_player_ids for player in players_who_can_act)

    def _require_positive_amount(self, amount: int | None) -> int:
        if type(amount) is not int or amount <= 0:
            raise ValueError("Amount must be a positive integer.")
        return amount

    def _resolve_all_in_showdown_if_closed(self, state: HandState) -> None:
        if state.result is not None:
            return

        live_players = [player for player in state.players if player.status != PlayerStatus.FOLDED]
        if len(live_players) < 2 or not any(player.status == PlayerStatus.ALL_IN for player in live_players):
            return

        if state.current_player_id is not None:
            current_player = self._get_player(state, state.current_player_id)
            if current_player.status != PlayerStatus.ACTIVE:
                return
            if self._call_amount(state, current_player) > 0:
                return
            if any(player.id != current_player.id and player.status != PlayerStatus.ALL_IN for player in live_players):
                return

        self._return_uncalled_bet(state)
        state.current_player_id = None

        cards_needed = 5 - len(state.board)
        if cards_needed > 0:
            state.board.extend(self._draw(cards_needed))
            state.notes.append("All-in runout dealt to showdown.")

        self._reset_street_bets(state)
        state.street = Street.SHOWDOWN
        self._resolve_showdown(state)

    def _return_uncalled_bet(self, state: HandState) -> None:
        sorted_bets = sorted(
            ((player.current_bet, player) for player in state.players),
            key=lambda item: item[0],
            reverse=True,
        )
        if len(sorted_bets) < 2:
            return

        highest_bet, highest_player = sorted_bets[0]
        second_highest_bet = sorted_bets[1][0]
        if highest_bet <= second_highest_bet:
            return

        excess = highest_bet - second_highest_bet
        highest_player.current_bet -= excess
        highest_player.stack += excess
        if highest_player.status == PlayerStatus.ALL_IN and highest_player.stack > 0:
            highest_player.status = PlayerStatus.ACTIVE
        state.pot -= excess
        state.notes.append(f"Returned uncalled bet of {excess} to {highest_player.name}.")

    def _starting_stacks(self, previous_state: HandState | None) -> dict[str, int]:
        if previous_state is None or previous_state.result is None:
            return {"hero": 1000, "villain": 1000}

        stacks = {player.id: player.stack for player in previous_state.players}

        return {
            "hero": self._rebuy_if_needed(stacks.get("hero", 1000), previous_state.big_blind),
            "villain": self._rebuy_if_needed(stacks.get("villain", 1000), previous_state.big_blind),
        }

    def _rebuy_if_needed(self, stack: int, big_blind: int) -> int:
        if stack < big_blind:
            return stack + 1000
        return stack

    def _next_dealer(self, previous_state: HandState | None) -> str:
        if previous_state is None or previous_state.result is None:
            return "hero"
        return "villain" if previous_state.dealer_player_id == "hero" else "hero"

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
        button_index = next(i for i, p in enumerate(state.players) if p.id == state.dealer_player_id)
        seat_order = state.players[button_index + 1:] + state.players[:button_index + 1]
        winner_ids = [p.id for p in seat_order if p in tied_winners]
        player_results: list[PlayerHandResult] = []

        for player in state.players:
            amount_won = 0
            outcome = "lose"

            if player.id in winner_ids:
                amount_won = share + (1 if winner_ids.index(player.id) < remainder else 0)
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
