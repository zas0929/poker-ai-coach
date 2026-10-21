import random
import unittest

from pydantic import ValidationError

from app.models.poker import ActionType as A, Card, PlayerActionRequest, PlayerStatus, Rank, Street, Suit
from app.services.betting_rules import betting_options
from app.services.hand_evaluator import HandEvaluator
from app.services.poker_engine import PokerEngine


class BettingRulesTest(unittest.TestCase):
    def setUp(self):
        self.engine = PokerEngine()
        self.state = self.engine.start_hand()

    def assert_rejected_unchanged(self, player, action, amount=None):
        before = self.state.model_dump()
        with self.assertRaises(ValueError):
            self.engine.apply_action(self.state, player, action, amount)
        self.assertEqual(self.state.model_dump(), before)

    def to_flop(self):
        self.engine.apply_action(self.state, self.state.current_player_id, A.CALL)
        self.engine.apply_action(self.state, self.state.current_player_id, A.CHECK)
        self.engine.advance(self.state)

    def test_correct_actor_on_all_streets_for_both_buttons(self):
        for button in ['hero', 'villain']:
            with self.subTest(button=button):
                if self.state.dealer_player_id != button:
                    if self.state.result is None:
                        self.engine.apply_action(self.state, self.state.current_player_id, A.FOLD)
                    self.state = self.engine.start_hand(self.state)
                self.assertEqual(self.state.current_player_id, button)
                nonbutton = 'villain' if button == 'hero' else 'hero'
                self.to_flop()
                for street in [Street.FLOP, Street.TURN, Street.RIVER]:
                    self.assertEqual(self.state.street, street)
                    self.assertEqual(self.state.current_player_id, nonbutton)
                    self.engine.apply_action(self.state, nonbutton, A.CHECK)
                    self.assertEqual(self.state.current_player_id, button)
                    self.engine.apply_action(self.state, button, A.CHECK)
                    self.assertIsNone(self.state.current_player_id)
                    self.engine.advance(self.state)
                self.assertIsNotNone(self.state.result)

    def test_minimum_raise_uses_increment_not_total_bet(self):
        self.engine.apply_action(self.state, 'hero', A.RAISE, 30)
        self.assertEqual(self.state.last_full_raise, 20)
        self.assertEqual(self.state.betting.min_raise_to, 50)
        self.engine.apply_action(self.state, 'villain', A.RAISE, 60)
        self.assertEqual(self.state.last_full_raise, 30)
        self.assertEqual(self.state.betting.min_raise_to, 90)
        self.engine.apply_action(self.state, 'hero', A.RAISE, 90)

    def test_underraise_is_rejected_before_mutation(self):
        self.engine.apply_action(self.state, 'hero', A.RAISE, 30)
        self.assert_rejected_unchanged('villain', A.RAISE, 40)

    def test_short_all_in_raise_leaves_only_call_or_fold(self):
        self.state.players[1].stack = 30
        initial_total = sum(p.stack for p in self.state.players) + self.state.pot
        self.engine.apply_action(self.state, 'hero', A.RAISE, 30)
        self.assertEqual(self.state.betting.min_raise_to, 40)
        self.engine.apply_action(self.state, 'villain', A.RAISE, 40)
        self.assertEqual(self.state.last_full_raise, 20)
        self.assertEqual(set(self.state.betting.legal_actions), {A.FOLD, A.CALL})
        self.assert_rejected_unchanged('hero', A.RAISE, 60)
        self.engine.apply_action(self.state, 'hero', A.CALL)
        self.assertIsNotNone(self.state.result)
        self.assertEqual(sum(p.stack for p in self.state.players), initial_total)

    def test_oversized_raise_is_not_silently_converted_to_short_call(self):
        self.state.players[0].stack = 2
        self.assert_rejected_unchanged('hero', A.RAISE, 100)
        self.engine.apply_action(self.state, 'hero', A.CALL)
        self.assertIsNotNone(self.state.result)
        self.assertEqual(self.state.players[1].status, PlayerStatus.ACTIVE)
        self.assertTrue(any('Returned uncalled bet' in note for note in self.state.notes))

    def test_opening_bet_has_big_blind_minimum(self):
        self.to_flop()
        self.assert_rejected_unchanged('villain', A.BET, 5)
        self.engine.apply_action(self.state, 'villain', A.BET, 10)
        self.assertEqual(self.state.betting.min_raise_to, 20)

    def test_short_opening_all_in_is_allowed(self):
        self.to_flop()
        self.state.players[1].stack = 5
        self.engine.apply_action(self.state, 'villain', A.BET, 5)
        self.assertEqual(self.state.players[1].status, PlayerStatus.ALL_IN)
        self.assertEqual(self.state.betting.call_amount, 5)
        self.assertNotIn(A.RAISE, self.state.betting.legal_actions)
        self.engine.apply_action(self.state, 'hero', A.CALL)
        self.assertIsNotNone(self.state.result)

    def test_raise_minimum_resets_each_street(self):
        self.engine.apply_action(self.state, 'hero', A.RAISE, 100)
        self.engine.apply_action(self.state, 'villain', A.CALL)
        self.engine.advance(self.state)
        self.assertEqual(self.state.last_full_raise, 10)
        self.engine.apply_action(self.state, 'villain', A.BET, 10)
        self.assertEqual(self.state.betting.min_raise_to, 20)

    def test_illegal_action_does_not_mutate_state(self):
        for player, action, amount in [
            ('villain', A.CALL, None), ('hero', A.CHECK, None),
            ('hero', A.BET, 30), ('hero', A.RAISE, -1),
            ('hero', A.RAISE, 0), ('hero', A.RAISE, 1001),
            ('hero', A.RAISE, 20.5), ('hero', A.RAISE, True),
        ]:
            with self.subTest(player=player, action=action, amount=amount):
                self.assert_rejected_unchanged(player, action, amount)

    def test_raise_requires_existing_bet(self):
        self.to_flop()
        self.assert_rejected_unchanged('villain', A.RAISE, 20)
        self.assert_rejected_unchanged('villain', A.CALL)

    def test_request_rejects_fractional_and_boolean_chip_amounts(self):
        for amount in [20.5, True, '20']:
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                PlayerActionRequest(action=A.RAISE, amount=amount)

    def test_cannot_deal_before_betting_closes(self):
        before = self.state.model_dump()
        with self.assertRaises(ValueError):
            self.engine.deal_flop(self.state)
        self.assertEqual(self.state.model_dump(), before)

    def test_fold_returns_unmatched_bet_and_settles_once(self):
        self.engine.apply_action(self.state, 'hero', A.RAISE, 100)
        self.engine.apply_action(self.state, 'villain', A.FOLD)
        self.assertEqual(self.state.result.pot_awarded, 20)
        self.assertEqual(self.state.players[0].stack, 1010)
        self.assertEqual(self.state.players[1].stack, 990)
        self.assertEqual(self.state.betting.legal_actions, [])
        before = self.state.model_dump()
        with self.assertRaises(ValueError):
            self.engine.advance(self.state)
        with self.assertRaises(ValueError):
            self.engine.deal_flop(self.state)
        with self.assertRaises(ValueError):
            self.engine.apply_action(self.state, 'hero', A.CHECK)
        self.engine.settle_all_in_if_ready(self.state)
        self.assertEqual(self.state.model_dump(), before)

    def test_cannot_replace_live_hand(self):
        before = self.state.model_dump()
        with self.assertRaises(ValueError):
            self.engine.start_hand(self.state)
        self.assertEqual(self.state.model_dump(), before)

    def test_odd_chip_goes_left_of_button_on_tied_board(self):
        self.state.street = Street.RIVER
        self.state.board = [Card(rank=Rank(r), suit=Suit.SPADES) for r in ['A', 'K', 'Q', 'J', 'T']]
        self.state.players[0].cards = [Card(rank=Rank.TWO, suit=Suit.CLUBS), Card(rank=Rank.THREE, suit=Suit.CLUBS)]
        self.state.players[1].cards = [Card(rank=Rank.FOUR, suit=Suit.CLUBS), Card(rank=Rank.FIVE, suit=Suit.CLUBS)]
        for button in ['hero', 'villain']:
            with self.subTest(button=button):
                state = self.state.model_copy(deep=True)
                state.dealer_player_id = button
                state.current_player_id = 'villain' if button == 'hero' else 'hero'
                state.history = []
                state.acted_at_bet = {}
                state.pot = 105
                for p in state.players:
                    p.current_bet = 0
                self.engine.apply_action(state, state.current_player_id, A.CHECK)
                self.engine.apply_action(state, state.current_player_id, A.CHECK)
                self.engine.advance(state)
                payouts = {p.player_id: p.amount_won for p in state.result.player_results}
                self.assertEqual(payouts[button], 52)
                self.assertEqual(payouts['villain' if button == 'hero' else 'hero'], 53)
                self.assertEqual(sum(payouts.values()), 105)

    def test_200_random_hands_preserve_chips_and_card_uniqueness(self):
        rng = random.Random(12345)
        state = None
        for _ in range(200):
            state = self.engine.start_hand(state)
            initial_total = state.pot + sum(p.stack for p in state.players)
            for turn in range(80):
                cards = state.board + [card for p in state.players for card in p.cards]
                self.assertEqual(len(cards), len({(c.rank, c.suit) for c in cards}))
                self.assertEqual(state.pot + sum(p.stack for p in state.players), initial_total)
                self.assertTrue(all(p.stack >= 0 for p in state.players))
                if state.result:
                    break
                if state.current_player_id is None:
                    self.engine.advance(state)
                    continue
                options = betting_options(state)
                # More passive actions let this exercise postflop flow as well as all-ins.
                choices = options.legal_actions + [a for a in options.legal_actions if a in {A.CHECK, A.CALL}] * 3
                action = rng.choice(choices)
                minimum = options.min_bet if action == A.BET else options.min_raise_to
                amount = rng.choice([minimum, options.max_raise_to]) if action in {A.BET, A.RAISE} else None
                self.engine.apply_action(state, state.current_player_id, action, amount)
            else:
                self.fail('Hand failed to terminate')


class EvaluatorControlTest(unittest.TestCase):
    def test_wheel_loses_to_six_high_straight(self):
        evaluator = HandEvaluator()
        wheel = [Card(rank=Rank(r), suit=Suit.SPADES if i % 2 else Suit.CLUBS) for i, r in enumerate(['A', '2', '3', '4', '5'])]
        six_high = [Card(rank=Rank(r), suit=Suit.SPADES if i % 2 else Suit.CLUBS) for i, r in enumerate(['2', '3', '4', '5', '6'])]
        self.assertEqual(evaluator.evaluate(wheel).kickers, [5])
        self.assertEqual(evaluator.compare(wheel, six_high), -1)


if __name__ == '__main__':
    unittest.main()
