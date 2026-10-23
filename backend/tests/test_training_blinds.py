import unittest
from fastapi import HTTPException
from app.api import hand
from app.models.poker import ActionType, PlayerActionRequest


class TrainingBlindTests(unittest.TestCase):
    def setUp(self):
        self.old_state = hand.current_state
        self.old_profiles = hand.profile_states.copy()
        self.binding = hand.training_owner.set(None)
        hand.current_state = None

    def tearDown(self):
        hand.current_state = self.old_state
        hand.profile_states.clear()
        hand.profile_states.update(self.old_profiles)
        hand.training_owner.reset(self.binding)

    def test_defaults_and_resume_preserve_selected_blinds(self):
        first = hand.start_hand(small_blind=2, big_blind=4)
        self.assertEqual((first.small_blind, first.big_blind), (2, 4))
        self.assertEqual(hand.start_hand().hand_id, first.hand_id)
        hand.apply_action(PlayerActionRequest(action=ActionType.FOLD))
        following = hand.start_hand()
        self.assertEqual((following.small_blind, following.big_blind), (2, 4))

    def test_changing_blinds_between_hands_preserves_stacks_and_rotates_button(self):
        first = hand.start_hand()
        self.assertEqual((first.small_blind, first.big_blind), (5, 10))
        hand.apply_action(PlayerActionRequest(action=ActionType.FOLD))
        stacks = {p.id: p.stack for p in hand.current_state.players}
        following = hand.start_hand(small_blind=1, big_blind=2)
        self.assertNotEqual(following.dealer_player_id, first.dealer_player_id)
        self.assertEqual(following.pot, 3)
        self.assertEqual({p.id: p.stack + p.current_bet for p in following.players}, stacks)
        self.assertEqual(sorted(following.contributions.values()), [1, 2])

    def test_active_hand_rejects_changes_without_touching_cards_pot_or_stacks(self):
        hand.start_hand()
        before = hand.current_state.model_dump_json()
        for values in [dict(small_blind=1, big_blind=2), dict(big_blind=20)]:
            with self.assertRaises(HTTPException) as caught:
                hand.start_hand(**values)
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(hand.current_state.model_dump_json(), before)
        self.assertEqual(hand.start_hand(small_blind=5, big_blind=10).model_dump_json(), before)

    def test_invalid_blinds_do_not_start_or_replace_a_hand(self):
        for small, big in [(0, 2), (1, 1), (5, 2), (1.5, 3), (True, 2), (1, 20001), (10001, 20000)]:
            with self.assertRaises(HTTPException) as caught:
                hand.start_hand(small_blind=small, big_blind=big)
            self.assertEqual(caught.exception.status_code, 400)
            self.assertIsNone(hand.current_state)

    def test_blinds_are_isolated_between_training_profiles(self):
        for owner, blinds in [('blind-alice', (1, 2)), ('blind-bob', (10, 20))]:
            token = hand.training_owner.set(owner)
            try:
                state = hand.start_hand(small_blind=blinds[0], big_blind=blinds[1])
                self.assertEqual((state.small_blind, state.big_blind), blinds)
            finally:
                hand.training_owner.reset(token)
        token = hand.training_owner.set('blind-alice')
        try:
            resumed = hand.start_hand()
            self.assertEqual((resumed.small_blind, resumed.big_blind), (1, 2))
        finally:
            hand.training_owner.reset(token)
