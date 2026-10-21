import unittest

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from app.api import hand
from app.models.poker import ActionType, PlayerActionRequest
from app.services.poker_engine import PokerEngine


class HandApiTest(unittest.TestCase):
    def setUp(self):
        self.previous_engine, self.previous_state = hand.engine, hand.current_state
        hand.engine, hand.current_state = PokerEngine(), None

    def tearDown(self):
        hand.engine, hand.current_state = self.previous_engine, self.previous_state

    def test_start_resumes_existing_hand_without_touching_deck(self):
        first = hand.start_hand()
        hand.apply_action(PlayerActionRequest(action=ActionType.RAISE, amount=30))
        before = first.model_dump()
        deck = list(hand.engine.deck)
        again = hand.start_hand()
        self.assertEqual(again.model_dump(), before)
        self.assertEqual(hand.engine.deck, deck)

    def test_rejected_action_is_400_and_preserves_state(self):
        state = hand.start_hand()
        before = state.model_dump()
        with self.assertRaises(HTTPException) as caught:
            hand.apply_action(PlayerActionRequest(action=ActionType.RAISE, amount=11))
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(state.model_dump(), before)

    def test_legal_actions_serialize_for_frontend_and_clear_after_fold(self):
        state = hand.start_hand()
        self.assertEqual(jsonable_encoder(state)['betting']['legal_actions'], ['fold', 'call', 'raise'])
        self.assertEqual(state.betting.min_raise_to, 20)
        hand.apply_action(PlayerActionRequest(action=ActionType.FOLD))
        self.assertEqual(jsonable_encoder(state)['betting']['legal_actions'], [])
        next_hand = hand.start_hand()
        self.assertNotEqual(state.hand_id, next_hand.hand_id)
        self.assertEqual(next_hand.dealer_player_id, 'villain')
