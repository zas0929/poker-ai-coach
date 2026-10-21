import unittest

from app.models.poker import ActionType, PlayerStatus, Street
from app.services.poker_engine import PokerEngine


class PokerEngineTest(unittest.TestCase):
    def test_big_blind_gets_preflop_option_after_small_blind_call(self):
        engine = PokerEngine()
        first_hand = engine.start_hand()
        first_hand.result = {
            "reason": "test",
            "winners": ["hero"],
            "pot_awarded": 0,
            "player_results": [],
        }
        state = engine.start_hand(previous_state=first_hand)

        self.assertEqual(state.dealer_player_id, "villain")
        state = engine.apply_action(state, "villain", ActionType.CALL)

        self.assertEqual(state.street.value, "preflop")
        self.assertEqual(state.current_player_id, "hero")
        self.assertEqual(len(state.board), 0)

        state = engine.apply_action(state, "hero", ActionType.CHECK)
        self.assertIsNone(state.current_player_id)

        state = engine.advance(state)
        self.assertEqual(state.street.value, "flop")
        self.assertEqual(len(state.board), 3)

    def test_short_all_in_call_returns_uncalled_bet_and_resolves(self):
        engine = PokerEngine()
        state = engine.start_hand()
        state.current_player_id = "villain"
        state.pot = 0
        state.street = Street.FLOP
        state.contributions = {p.id: 0 for p in state.players}
        for player in state.players:
            player.current_bet = 0

        hero = next(player for player in state.players if player.id == "hero")
        villain = next(player for player in state.players if player.id == "villain")
        hero.stack = 1000
        villain.stack = 2000

        state = engine.apply_action(state, "villain", ActionType.BET, 1280)
        self.assertEqual(state.current_player_id, "hero")
        self.assertEqual(state.pot, 1280)

        state = engine.apply_action(state, "hero", ActionType.CALL)

        self.assertEqual(state.street.value, "showdown")
        self.assertIsNone(state.current_player_id)
        self.assertIsNotNone(state.result)
        self.assertEqual(len(state.board), 5)
        self.assertTrue(any("Returned uncalled bet" in note for note in state.notes))

    def test_stuck_all_in_ai_turn_state_can_be_settled(self):
        engine = PokerEngine()
        state = engine.start_hand()
        state.current_player_id = "villain"
        state.pot = 2280
        state.contributions = {"hero": 1000, "villain": 1280}
        for player in state.players:
            player.current_bet = 0

        hero = next(player for player in state.players if player.id == "hero")
        villain = next(player for player in state.players if player.id == "villain")
        hero.stack = 0
        hero.current_bet = 1000
        hero.status = PlayerStatus.ALL_IN
        villain.stack = 720
        villain.current_bet = 1280

        state = engine.settle_all_in_if_ready(state)

        self.assertEqual(state.street.value, "showdown")
        self.assertIsNone(state.current_player_id)
        self.assertIsNotNone(state.result)
        self.assertEqual(len(state.board), 5)


if __name__ == "__main__":
    unittest.main()
