import unittest
from app.services.decision_engine import DecisionEngine
from app.services.poker_engine import PokerEngine
from app.models.poker import ActionType


class CoachSizingTests(unittest.TestCase):
    def test_preflop_size_and_passive_advice(self):
        state = PokerEngine().start_hand()
        self.assertEqual(DecisionEngine.recommended_size(state, 'hero', 'raise'), 30)
        self.assertIsNone(DecisionEngine.recommended_size(state, 'hero', 'call'))

    def test_short_stack_size_is_legal_all_in(self):
        state = PokerEngine().start_hand()
        state.players[0].stack = 11
        PokerEngine()._refresh_betting(state)
        self.assertEqual(DecisionEngine.recommended_size(state, 'hero', 'raise'), 16)

    def test_postflop_size_and_raise_total(self):
        engine = PokerEngine()
        state = engine.start_hand()
        state = engine.apply_action(state, 'hero', ActionType.CALL)
        state = engine.apply_action(state, state.current_player_id, ActionType.CHECK)
        state = engine.advance(state)
        actor = state.current_player_id
        self.assertEqual(DecisionEngine.recommended_size(state, actor, 'bet'), 13)
        state = engine.apply_action(state, actor, ActionType.BET, 10)
        self.assertEqual(DecisionEngine.recommended_size(state, state.current_player_id, 'raise'), 37)
