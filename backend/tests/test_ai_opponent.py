import unittest

from app.models.poker import ActionType, Card, Rank, Suit
from app.services.ai_opponent import AIOpponentService
from app.services.decision_engine import DecisionEngine
from app.services.poker_engine import PokerEngine


class AIOpponentServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = PokerEngine()
        self.decision_engine = DecisionEngine()
        self.ai = AIOpponentService(profile="balanced")

    def test_premium_preflop_hand_raises_facing_action(self):
        state = self.engine.start_hand()
        villain = next(player for player in state.players if player.id == "villain")
        villain.cards = [
            Card(rank=Rank.ACE, suit=Suit.SPADES),
            Card(rank=Rank.ACE, suit=Suit.HEARTS),
        ]
        state.current_player_id = "villain"
        villain.current_bet = 10
        hero = next(player for player in state.players if player.id == "hero")
        hero.current_bet = 30

        analysis = self.decision_engine.analyze(state, player_id="villain")
        decision = self.ai.choose_action(state, analysis, player_id="villain")

        self.assertEqual(decision.action, ActionType.RAISE)
        self.assertIsNotNone(decision.amount)
        self.assertGreater(decision.amount or 0, hero.current_bet)

    def test_weak_preflop_hand_folds_to_raise(self):
        state = self.engine.start_hand()
        villain = next(player for player in state.players if player.id == "villain")
        villain.cards = [
            Card(rank=Rank.SEVEN, suit=Suit.SPADES),
            Card(rank=Rank.TWO, suit=Suit.HEARTS),
        ]
        state.current_player_id = "villain"
        villain.current_bet = 10
        hero = next(player for player in state.players if player.id == "hero")
        hero.current_bet = 80

        analysis = self.decision_engine.analyze(state, player_id="villain")
        decision = self.ai.choose_action(state, analysis, player_id="villain")

        self.assertEqual(decision.action, ActionType.FOLD)

    def test_big_blind_raises_premium_hand_after_limp(self):
        state = self.engine.start_hand()
        state = self.engine.apply_action(state, "hero", ActionType.CALL)
        villain = next(player for player in state.players if player.id == "villain")
        villain.cards = [Card(rank=Rank.ACE, suit=Suit.SPADES), Card(rank=Rank.ACE, suit=Suit.HEARTS)]
        analysis = self.decision_engine.analyze(state, player_id="villain")
        decision = self.ai.choose_action(state, analysis, player_id="villain")
        self.assertEqual(decision.action, ActionType.RAISE)
        self.engine.apply_action(state, "villain", decision.action, decision.amount)


if __name__ == "__main__":
    unittest.main()
