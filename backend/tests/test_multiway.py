import random
import unittest

from fastapi import HTTPException
from app.api import hand
from app.models.poker import ActionType as A, Card, PlayerStatus, Rank, Street, Suit
from app.services.betting_rules import betting_options
from app.services.decision_engine import DecisionEngine
from app.services.equity_service import EquityService
from app.services.poker_engine import PokerEngine
from app.services.range_service import RangeService


def card(text):
    return Card(rank=Rank(text[0]), suit={'s': Suit.SPADES, 'h': Suit.HEARTS, 'd': Suit.DIAMONDS, 'c': Suit.CLUBS}[text[1]])


def controlled_runout(state, holdings, board=('2c', '4d', '7h', '9s', 'Jc')):
    for player, cards in zip(state.players, holdings):
        player.cards = [card(c) for c in cards]
    board = [card(c) for c in board]
    used = {(c.rank, c.suit) for p in state.players for c in p.cards} | {(c.rank, c.suit) for c in board}
    state._deck = [Card(rank=r, suit=s) for r in Rank for s in Suit if (r, s) not in used] + list(reversed(board))


class MultiwayEngineTest(unittest.TestCase):
    def test_preflop_order_and_button_rotation_for_every_table_size(self):
        for size in range(2, 7):
            engine = PokerEngine()
            state = None
            for expected_button in range(size):
                state = engine.start_hand(state, player_count=size)
                self.assertEqual(state.dealer_player_id, state.players[expected_button].id)
                expected_first = expected_button if size == 2 else (expected_button + 3) % size
                self.assertEqual(state.current_player_id, state.players[expected_first].id)
                initial = state.pot + sum(p.stack for p in state.players)
                for _ in range(size):
                    current = state.current_player_id
                    options = state.betting
                    engine.apply_action(state, current, A.CALL if options.call_amount else A.CHECK)
                self.assertIsNone(state.current_player_id)
                engine.advance(state)
                self.assertEqual(state.current_player_id, state.players[(expected_button + 1) % size].id)
                while not state.result:
                    if state.current_player_id is None:
                        engine.advance(state)
                    else:
                        engine.apply_action(state, state.current_player_id, A.FOLD)
                self.assertEqual(sum(p.stack for p in state.players), initial)

    def test_main_and_side_pot_have_different_winners(self):
        engine = PokerEngine()
        state = engine.start_hand(player_count=3, starting_stacks=[50, 100, 200])
        controlled_runout(state, [('As', 'Ah'), ('Ks', 'Kh'), ('Qs', 'Qh')])
        engine.apply_action(state, 'hero', A.RAISE, 50)
        engine.apply_action(state, 'villain', A.RAISE, 100)
        engine.apply_action(state, 'villain_2', A.CALL)
        self.assertEqual(state.result.pot_awarded, 250)
        self.assertEqual([p.amount for p in state.result.pots], [150, 100])
        self.assertEqual(state.result.pots[0].winners, ['hero'])
        self.assertEqual(state.result.pots[1].winners, ['villain'])
        self.assertEqual([p.stack for p in state.players], [150, 100, 100])
        self.assertNotIn('hero', state.result.pots[1].eligible_player_ids)

    def test_three_pots_include_a_split_side_pot(self):
        engine = PokerEngine()
        state = engine.start_hand(player_count=4, starting_stacks=[50, 100, 150, 200])
        controlled_runout(state, [('As', 'Ah'), ('Kc', 'Kd'), ('Kh', 'Ks'), ('Qc', 'Qd')])
        engine.apply_action(state, 'villain_3', A.RAISE, 200)
        for pid in ['hero', 'villain', 'villain_2']:
            engine.apply_action(state, pid, A.CALL)
        self.assertEqual([p.amount for p in state.result.pots], [200, 150, 100])
        self.assertEqual(state.result.pots[1].awards, {'villain': 75, 'villain_2': 75})
        self.assertEqual([p.stack for p in state.players], [200, 75, 175, 50])

    def test_excess_all_in_is_returned_before_side_pots(self):
        engine = PokerEngine()
        state = engine.start_hand(player_count=3, starting_stacks=[200, 50, 100])
        controlled_runout(state, [('As', 'Ah'), ('Ks', 'Kh'), ('Qs', 'Qh')])
        engine.apply_action(state, 'hero', A.RAISE, 200)
        engine.apply_action(state, 'villain', A.CALL)
        engine.apply_action(state, 'villain_2', A.CALL)
        self.assertEqual(state.result.pot_awarded, 250)
        self.assertEqual(state.contributions, {'hero': 100, 'villain': 50, 'villain_2': 100})
        self.assertEqual(state.players[0].stack, 350)
        self.assertEqual(sum(p.stack for p in state.players), 350)

    def test_folded_money_stays_in_pot_but_cannot_win(self):
        engine = PokerEngine()
        state = engine.start_hand(player_count=3)
        controlled_runout(state, [('As', 'Ah'), ('Ks', 'Kh'), ('Qs', 'Qh')])
        engine.apply_action(state, 'hero', A.RAISE, 50)
        engine.apply_action(state, 'villain', A.CALL)
        engine.apply_action(state, 'villain_2', A.RAISE, 100)
        engine.apply_action(state, 'hero', A.FOLD)
        self.assertIsNone(state.result)
        engine.apply_action(state, 'villain', A.CALL)
        while not state.result:
            if state.current_player_id is None:
                engine.advance(state)
            else:
                engine.apply_action(state, state.current_player_id, A.CHECK)
        self.assertEqual(state.result.pot_awarded, 250)
        self.assertEqual(len(state.result.pots), 1)
        self.assertEqual(state.result.winners, ['villain'])
        self.assertEqual(state.result.player_results[0].outcome, 'folded')
        self.assertEqual(sum(p.stack for p in state.players), 3000)

    def test_all_in_does_not_end_betting_between_funded_players(self):
        engine = PokerEngine()
        state = engine.start_hand(player_count=3, starting_stacks=[50, 500, 500])
        engine.apply_action(state, 'hero', A.RAISE, 50)
        engine.apply_action(state, 'villain', A.CALL)
        engine.apply_action(state, 'villain_2', A.CALL)
        self.assertIsNone(state.result)
        engine.advance(state)
        self.assertEqual(state.current_player_id, 'villain')
        engine.apply_action(state, 'villain', A.BET, 100)
        engine.apply_action(state, 'villain_2', A.CALL)
        self.assertIsNone(state.result)
        self.assertEqual(state.contributions, {'hero': 50, 'villain': 150, 'villain_2': 150})

    def test_cumulative_short_all_ins_reopen_a_full_raise(self):
        engine = PokerEngine()
        state = engine.start_hand(player_count=5, starting_stacks=[130, 190, 1000, 1000, 1000])
        engine.apply_action(state, 'villain_3', A.RAISE, 100)
        engine.apply_action(state, 'villain_4', A.CALL)
        engine.apply_action(state, 'hero', A.RAISE, 130)
        engine.apply_action(state, 'villain', A.RAISE, 190)
        engine.apply_action(state, 'villain_2', A.CALL)
        self.assertEqual(state.current_player_id, 'villain_3')
        self.assertEqual(state.last_full_raise, 90)
        self.assertIn(A.RAISE, state.betting.legal_actions)
        self.assertEqual(state.betting.min_raise_to, 280)
        engine.apply_action(state, 'villain_3', A.RAISE, 280)

    def test_one_short_raise_does_not_reopen_prior_actor(self):
        engine = PokerEngine()
        state = engine.start_hand(player_count=5, starting_stacks=[1000, 1000, 1000, 1000, 130])
        engine.apply_action(state, 'villain_3', A.RAISE, 100)
        engine.apply_action(state, 'villain_4', A.RAISE, 130)
        for pid in ['hero', 'villain', 'villain_2']:
            engine.apply_action(state, pid, A.CALL)
        self.assertEqual(state.current_player_id, 'villain_3')
        self.assertEqual(state.betting.legal_actions, [A.FOLD, A.CALL])
        before = state.model_dump()
        with self.assertRaises(ValueError):
            engine.apply_action(state, 'villain_3', A.RAISE, 220)
        self.assertEqual(state.model_dump(), before)

    def test_short_big_blind_preserves_full_bring_in(self):
        state = PokerEngine().start_hand(player_count=3, starting_stacks=[1000, 1000, 3])
        self.assertEqual(state.betting.call_amount, 10)
        self.assertEqual(state.betting.min_raise_to, 20)

    def test_decks_are_per_hand_and_never_serialize(self):
        engine = PokerEngine()
        first = engine.start_hand(player_count=6)
        first_deck = list(first._deck)
        second = engine.start_hand(player_count=3)
        self.assertEqual(first._deck, first_deck)
        self.assertIsNot(first._deck, second._deck)
        self.assertNotIn('_deck', first.model_dump())
        self.assertEqual(len(first._deck), 40)

    def test_500_random_hands_across_table_sizes_conserve_every_chip(self):
        rng = random.Random(8675309)
        for size in range(2, 7):
            engine = PokerEngine()
            for _ in range(100):
                stacks = [rng.choice([3, 5, 10, 35, 80, 200, 1000]) for _ in range(size)]
                state = engine.start_hand(player_count=size, starting_stacks=stacks)
                for _ in range(150):
                    self.assertEqual(state.pot + sum(p.stack for p in state.players), sum(stacks))
                    self.assertTrue(all(p.stack >= 0 for p in state.players))
                    cards = state.board + [c for p in state.players for c in p.cards]
                    self.assertEqual(len(cards), len({(c.rank, c.suit) for c in cards}))
                    if state.result:
                        self.assertEqual(sum(p.amount for p in state.result.pots), state.result.pot_awarded)
                        break
                    self.assertEqual(sum(state.contributions.values()), state.pot)
                    if state.current_player_id is None:
                        engine.advance(state)
                        continue
                    options = state.betting
                    choices = options.legal_actions + [a for a in options.legal_actions if a in {A.CALL, A.CHECK}] * 3
                    action = rng.choice(choices)
                    minimum = options.min_bet if action == A.BET else options.min_raise_to
                    amount = rng.choice([minimum, options.max_raise_to]) if action in {A.BET, A.RAISE} else None
                    engine.apply_action(state, state.current_player_id, action, amount)
                else:
                    self.fail('Hand did not terminate')

    def test_reject_invalid_table_size_before_deck_mutation(self):
        engine = PokerEngine()
        deck = list(engine.deck)
        for count in [1, 7, True, 3.5]:
            with self.assertRaises(ValueError):
                engine.start_hand(player_count=count)
            self.assertEqual(engine.deck, deck)


class MultiwayEquityTest(unittest.TestCase):
    def test_shared_royal_flush_is_one_third_not_one_half(self):
        state = PokerEngine().start_hand(player_count=3)
        state.board = [card(c) for c in ['As', 'Ks', 'Qs', 'Js', 'Ts']]
        state.players[0].cards = [card('2c'), card('3c')]
        estimate = EquityService().estimate(state, simulations=50)
        self.assertEqual(estimate.equity, 0.3333)
        self.assertEqual(estimate.method, 'monte_carlo_multiway')

    def test_multiway_equity_ignores_hidden_cards(self):
        state = PokerEngine().start_hand(player_count=3)
        state.board = [card(c) for c in ['2c', '7d', 'Jh']]
        state.players[0].cards = [card('As'), card('Ah')]
        before = EquityService().estimate(state, simulations=100)
        for p in state.players[1:]:
            p.cards = [card('3s'), card('3h')]
        after = EquityService().estimate(state, simulations=100)
        self.assertEqual(before, after)

    def test_folded_player_is_not_an_active_equity_opponent(self):
        state = PokerEngine().start_hand(player_count=3)
        state.board = [card(c) for c in ['As', 'Ks', 'Qs', 'Js', 'Ts']]
        state.players[0].cards = [card('2c'), card('3c')]
        state.players[2].status = PlayerStatus.FOLDED
        estimate = EquityService().estimate(state)
        self.assertEqual(estimate.equity, 0.5)
        self.assertEqual(estimate.method, 'exact_river')

    def test_multiway_analysis_lists_each_range_and_does_not_invent_side_pot_ev(self):
        state = PokerEngine().start_hand(player_count=3)
        analysis = DecisionEngine().analyze(state)
        self.assertEqual(analysis.opponent_count, 2)
        self.assertEqual({r.player_id for r in analysis.opponent_ranges}, {'villain', 'villain_2'})
        self.assertFalse(analysis.call_ev_available)
        self.assertIn(analysis.recommended_action, state.betting.legal_actions)


class MultiwayApiTest(unittest.TestCase):
    def setUp(self):
        self.saved = hand.engine, hand.current_state
        hand.engine, hand.current_state = PokerEngine(), None

    def tearDown(self):
        hand.engine, hand.current_state = self.saved

    def test_start_six_and_reject_count_change_mid_hand(self):
        state = hand.start_hand(player_count=6)
        self.assertEqual(len(state.players), 6)
        self.assertEqual(hand.start_hand().hand_id, state.hand_id)
        with self.assertRaises(HTTPException) as error:
            hand.start_hand(player_count=3)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(hand.current_state.hand_id, state.hand_id)

    def test_auto_play_runs_every_nonhero_seat(self):
        state = hand.start_hand(player_count=4)
        state = hand.auto_play_until_hero()
        self.assertTrue(state.result or state.current_player_id == 'hero')
        self.assertTrue(any(a.player_id == 'villain_3' for a in state.history))


if __name__ == '__main__':
    unittest.main()
