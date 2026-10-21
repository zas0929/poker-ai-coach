from __future__ import annotations

import secrets
import uuid

from app.models.poker import (
    ActionType, Card, HandAction, HandResult, HandState, Player,
    PlayerHandResult, PlayerStatus, PotResult, Rank, Street, Suit,
)
from app.services.betting_rules import betting_options, highest_bet
from app.services.hand_evaluator import HandEvaluator


class PokerEngine:
    def __init__(self):
        # Compatibility handle for local diagnostics; each hand owns its deck.
        self.deck: list[Card] = self._create_deck()
        self.evaluator = HandEvaluator()

    def _create_deck(self) -> list[Card]:
        return [Card(rank=rank, suit=suit) for rank in Rank for suit in Suit]

    def _draw(self, count: int, state: HandState | None = None) -> list[Card]:
        deck = state._deck if state is not None else self.deck
        if len(deck) < count:
            raise ValueError("Not enough cards remain in this hand's deck.")
        return [deck.pop() for _ in range(count)]

    def start_hand(
        self, previous_state: HandState | None = None, player_count: int | None = None,
        starting_stacks: list[int] | None = None,
    ) -> HandState:
        if previous_state is not None and previous_state.result is None:
            raise ValueError("Finish the current hand before starting another.")
        count = player_count if player_count is not None else len(previous_state.players) if previous_state else 2
        if type(count) is not int or not 2 <= count <= 6:
            raise ValueError("Player count must be between 2 and 6.")
        if starting_stacks is not None and (
            len(starting_stacks) != count or any(type(s) is not int or s <= 0 for s in starting_stacks)
        ):
            raise ValueError("Provide one positive integer starting stack per player.")
        continuing = previous_state is not None and len(previous_state.players) == count and starting_stacks is None
        ids = ['hero', 'villain', *[f'villain_{i}' for i in range(2, count)]]
        button = (ids.index(previous_state.dealer_player_id) + 1) % count if continuing else 0
        sb, bb = (button, (button + 1) % count) if count == 2 else ((button + 1) % count, (button + 2) % count)
        stacks = starting_stacks or [
            self._rebuy_if_needed(previous_state.players[i].stack, 10) if continuing else 1000
            for i in range(count)
        ]
        self.deck = self._create_deck()
        secrets.SystemRandom().shuffle(self.deck)
        players = [Player(id=pid, name='You' if i == 0 else f'AI {i}', stack=stacks[i],
                          position=self._position(i, button, count), cards=[])
                   for i, pid in enumerate(ids)]
        # Deal clockwise from the first seat left of the button, one card per round.
        for _ in range(2):
            for offset in range(1, count + 1):
                players[(button + offset) % count].cards.extend(self._draw(1))
        state = HandState(
            hand_id=str(uuid.uuid4()), street=Street.PREFLOP, pot=0,
            small_blind=5, big_blind=10, last_full_raise=10, players=players,
            dealer_player_id=ids[button], contributions={pid: 0 for pid in ids},
            notes=[f'New {count}-player training hand. Button: {ids[button]}.'],
        )
        state._deck = self.deck
        for index, blind, label in [(sb, 5, 'small_blind'), (bb, 10, 'big_blind')]:
            committed = self._commit_chips(state, players[index], blind)
            state.history.append(HandAction(player_id=ids[index], action=label, amount=committed, street=Street.PREFLOP))
        first = button if count == 2 else (bb + 1) % count
        state.current_player_id = self._next_pending(state, ids[(first - 1) % count])
        self._resolve_all_in_showdown_if_closed(state)
        return self._refresh_betting(state)

    @staticmethod
    def _position(index: int, button: int, count: int) -> str:
        offset = (index - button) % count
        if count == 2:
            return 'small_blind_button' if offset == 0 else 'big_blind'
        return {0: 'button', 1: 'small_blind', 2: 'big_blind', 3: 'under_the_gun',
                4: 'cutoff' if count == 5 else 'hijack', 5: 'cutoff'}[offset]

    def deal_flop(self, state: HandState) -> HandState:
        return self._deal_street(state, Street.PREFLOP, Street.FLOP, 3)

    def deal_turn(self, state: HandState) -> HandState:
        return self._deal_street(state, Street.FLOP, Street.TURN, 1)

    def deal_river(self, state: HandState) -> HandState:
        return self._deal_street(state, Street.TURN, Street.RIVER, 1)

    def _deal_street(self, state: HandState, expected: Street, following: Street, count: int) -> HandState:
        self._ensure_open_hand(state)
        if state.street != expected:
            raise ValueError(f'Expected {expected.value} street.')
        self._ensure_round_closed(state)
        self._return_uncalled_bet(state)
        self._resolve_all_in_showdown_if_closed(state)
        if state.result:
            return self._refresh_betting(state)
        cards = self._draw(count, state)
        self._reset_street_bets(state)
        state.board.extend(cards)
        state.street = following
        state.current_player_id = self._next_pending(state, state.dealer_player_id)
        state.notes.append(f'{following.value.title()} dealt.')
        return self._refresh_betting(state)

    def advance(self, state: HandState) -> HandState:
        self._ensure_open_hand(state)
        self._ensure_round_closed(state)
        self._resolve_all_in_showdown_if_closed(state)
        if state.result:
            return self._refresh_betting(state)
        if state.street == Street.PREFLOP:
            return self.deal_flop(state)
        if state.street == Street.FLOP:
            return self.deal_turn(state)
        if state.street == Street.TURN:
            return self.deal_river(state)
        self._return_uncalled_bet(state)
        self._reset_street_bets(state)
        state.street = Street.SHOWDOWN
        state.current_player_id = None
        self._resolve_showdown(state)
        return self._refresh_betting(state)

    def settle_all_in_if_ready(self, state: HandState) -> HandState:
        self._resolve_all_in_showdown_if_closed(state)
        return self._refresh_betting(state)

    def apply_action(self, state: HandState, player_id: str, action: ActionType, amount: int | None = None) -> HandState:
        self._ensure_open_hand(state)
        if state.current_player_id != player_id:
            raise ValueError(f"It is {state.current_player_id}'s turn, not {player_id}'s.")
        player = self._get_player(state, player_id)
        options = betting_options(state, player_id)
        if action not in options.legal_actions:
            raise ValueError(f'Action {action.value} is not legal in the current state.')
        if action in {ActionType.BET, ActionType.RAISE}:
            minimum = options.min_bet if action == ActionType.BET else options.min_raise_to
            if type(amount) is not int or minimum is None or not minimum <= amount <= options.max_raise_to:
                raise ValueError(f'Amount must be an integer between {minimum} and {options.max_raise_to}.')

        if action == ActionType.FOLD:
            player.status = PlayerStatus.FOLDED
            state.history.append(HandAction(player_id=player_id, action=action.value, street=state.street))
            if len(self._live_players(state)) == 1:
                self._return_uncalled_bet(state)
                self._resolve_fold(state)
                return self._refresh_betting(state)
        elif action in {ActionType.CHECK, ActionType.CALL}:
            committed = self._commit_chips(state, player, options.call_amount) if action == ActionType.CALL else None
            state.acted_at_bet[player_id] = self._highest_bet(state)
            state.history.append(HandAction(player_id=player_id, action=action.value, amount=committed, street=state.street))
        else:
            increment = amount - self._highest_bet(state)
            if increment >= max(state.big_blind, state.last_full_raise):
                state.last_full_raise = increment
            committed = self._commit_chips(state, player, amount - player.current_bet)
            state.acted_at_bet[player_id] = amount
            state.history.append(HandAction(player_id=player_id, action=action.value, amount=committed, street=state.street))

        state.current_player_id = self._next_pending(state, player_id)
        if state.current_player_id is None:
            self._return_uncalled_bet(state)
        self._resolve_all_in_showdown_if_closed(state)
        return self._refresh_betting(state)

    def _next_pending(self, state: HandState, after: str) -> str | None:
        active = [p for p in state.players if p.status == PlayerStatus.ACTIVE and p.stack > 0]
        highest = self._highest_bet(state)
        # With only one funded player, only a response to an outstanding bet is needed.
        if len(active) == 1 and active[0].current_bet >= highest:
            return None
        start = next(i for i, p in enumerate(state.players) if p.id == after)
        for offset in range(1, len(state.players) + 1):
            player = state.players[(start + offset) % len(state.players)]
            if player in active and (player.current_bet < highest or player.id not in state.acted_at_bet):
                return player.id
        return None

    def _refresh_betting(self, state: HandState) -> HandState:
        state.betting = betting_options(state)
        return state

    @staticmethod
    def _ensure_open_hand(state: HandState) -> None:
        if not 2 <= len(state.players) <= 6:
            raise ValueError('Tables support 2–6 players.')
        if state.result is not None or state.street == Street.SHOWDOWN:
            raise ValueError('Hand is already finished.')

    @staticmethod
    def _ensure_round_closed(state: HandState) -> None:
        if state.current_player_id is not None:
            raise ValueError('Cannot advance while betting action is still open.')

    @staticmethod
    def _reset_street_bets(state: HandState) -> None:
        state.last_full_raise = state.big_blind
        state.acted_at_bet.clear()
        for player in state.players:
            player.current_bet = 0

    @staticmethod
    def _get_player(state: HandState, player_id: str) -> Player:
        for player in state.players:
            if player.id == player_id:
                return player
        raise ValueError(f'Player {player_id} was not found.')

    @staticmethod
    def _live_players(state: HandState) -> list[Player]:
        return [p for p in state.players if p.status != PlayerStatus.FOLDED]

    @staticmethod
    def _highest_bet(state: HandState) -> int:
        return highest_bet(state)

    def _commit_chips(self, state: HandState, player: Player, amount: int) -> int:
        if type(amount) is not int or amount <= 0:
            raise ValueError('Chip commitment must be a positive integer.')
        committed = min(amount, player.stack)
        player.stack -= committed
        player.current_bet += committed
        state.contributions[player.id] = state.contributions.get(player.id, 0) + committed
        state.pot += committed
        if player.stack == 0:
            player.status = PlayerStatus.ALL_IN
        return committed

    def _resolve_all_in_showdown_if_closed(self, state: HandState) -> None:
        if state.result is not None:
            return
        live = self._live_players(state)
        active = [p for p in live if p.status == PlayerStatus.ACTIVE and p.stack > 0]
        if len(live) < 2 or not any(p.status == PlayerStatus.ALL_IN for p in live) or len(active) > 1:
            return
        if active and active[0].current_bet < self._highest_bet(state):
            return
        self._return_uncalled_bet(state)
        state.current_player_id = None
        needed = 5 - len(state.board)
        if needed:
            state.board.extend(self._draw(needed, state))
            state.notes.append('All-in runout dealt to showdown.')
        self._reset_street_bets(state)
        state.street = Street.SHOWDOWN
        self._resolve_showdown(state)

    def _return_uncalled_bet(self, state: HandState) -> None:
        ordered = sorted(state.players, key=lambda p: p.current_bet, reverse=True)
        high, runner_up = ordered[:2]
        excess = high.current_bet - runner_up.current_bet
        if excess <= 0:
            return
        high.current_bet -= excess
        high.stack += excess
        state.contributions[high.id] -= excess
        state.pot -= excess
        if high.status == PlayerStatus.ALL_IN and high.stack > 0:
            high.status = PlayerStatus.ACTIVE
        state.notes.append(f'Returned uncalled bet of {excess} to {high.name}.')

    @staticmethod
    def _rebuy_if_needed(stack: int, big_blind: int) -> int:
        return stack + 1000 if stack < big_blind else stack

    def _resolve_fold(self, state: HandState) -> None:
        winner = self._live_players(state)[0]
        amount = state.pot
        winner.stack += amount
        state.pot = 0
        state.current_player_id = None
        state.result = HandResult(
            reason='fold', winners=[winner.id], pot_awarded=amount,
            player_results=[PlayerHandResult(player_id=p.id, outcome='win' if p.id == winner.id else 'folded',
                                             amount_won=amount if p.id == winner.id else 0) for p in state.players],
            pots=[PotResult(amount=amount, eligible_player_ids=[winner.id], winners=[winner.id], awards={winner.id: amount})],
        )
        self._reset_street_bets(state)

    def _resolve_showdown(self, state: HandState) -> None:
        if state.result is not None:
            return
        if sum(state.contributions.values()) != state.pot:
            raise ValueError('Pot does not match player contributions.')
        live = self._live_players(state)
        strengths = {p.id: self.evaluator.evaluate([*p.cards, *state.board]) for p in live}
        scores = {pid: (s.rank, s.kickers) for pid, s in strengths.items()}
        button = next(i for i, p in enumerate(state.players) if p.id == state.dealer_player_id)
        seats = state.players[button + 1:] + state.players[:button + 1]
        pots = []
        layers: list[tuple[int, list[str]]] = []
        awards = {p.id: 0 for p in state.players}
        prior = 0
        for level in sorted(set(state.contributions.values()) - {0}):
            contributors = [p for p in state.players if state.contributions.get(p.id, 0) >= level]
            amount = (level - prior) * len(contributors)
            prior = level
            eligible = [p.id for p in contributors if p.status != PlayerStatus.FOLDED]
            if not eligible:
                raise ValueError('A pot has no eligible player.')
            if layers and layers[-1][1] == eligible:
                layers[-1] = (layers[-1][0] + amount, eligible)
            else:
                layers.append((amount, eligible))
        for amount, eligible in layers:
            best = max(scores[pid] for pid in eligible)
            winners = [p.id for p in seats if p.id in eligible and scores[p.id] == best]
            share, remainder = divmod(amount, len(winners))
            payouts = {pid: share + (i < remainder) for i, pid in enumerate(winners)}
            for pid, payout in payouts.items():
                awards[pid] += payout
            pots.append(PotResult(amount=amount, eligible_player_ids=eligible, winners=winners, awards=payouts))
        # Complete and validate all pots before changing any player's stack.
        for player in state.players:
            player.stack += awards[player.id]
        winner_ids = [p.id for p in seats if awards[p.id] > 0]
        state.result = HandResult(
            reason='showdown', winners=winner_ids, pot_awarded=state.pot, pots=pots,
            player_results=[PlayerHandResult(
                player_id=p.id, amount_won=awards[p.id], hand_strength=strengths.get(p.id),
                outcome='folded' if p.status == PlayerStatus.FOLDED else
                        ('tie' if all(len(pot.winners) > 1 for pot in pots if p.id in pot.winners) else 'win')
                        if awards[p.id] > 0 else 'lose',
            ) for p in state.players],
        )
        state.pot = 0
        state.notes.append(f'Showdown: {len(pots)} pot(s) awarded.')
