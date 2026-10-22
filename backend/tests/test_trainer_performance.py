import random
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from fastapi import HTTPException

from app.api import hand as api
from app.models.poker import ActionType, Card, PlayerActionRequest, Rank, Suit
from app.services.ai_opponent import AIOpponentService
from app.services.decision_engine import DecisionEngine
from app.services.hand_evaluator import HandEvaluator
from app.services.poker_engine import PokerEngine


class FastScoreTests(unittest.TestCase):
    def test_matches_best_five_reference_on_seeded_five_six_and_seven_card_hands(self):
        evaluator = HandEvaluator()
        deck = [Card(rank=r, suit=s) for r in Rank for s in Suit]
        rng = random.Random(71823)
        for size in (5, 6, 7):
            for _ in range(3000):
                cards = rng.sample(deck, size)
                reference = evaluator.evaluate(cards)
                self.assertEqual(evaluator.score(cards), (reference.rank, reference.kickers), cards)

    def test_seven_card_edge_cases(self):
        cases = [
            ('As 2h 3d 4c 5s 6h 7d', (4, [7])),
            ('As 2s 3s 4s 5s 6s 9h', (8, [6])),
            ('Ah Ad Ac Kh Kd Kc 2s', (6, [14, 13])),
            ('Ah Ad Kh Kd Qh Qd 2s', (2, [14, 13, 12])),
            ('As Ks 9s 7s 4s 3s 2s', (5, [14, 13, 9, 7, 4])),
            ('Ah Ad Ac As Kh Kd 2s', (7, [14, 13])),
        ]
        suits = dict(s=Suit.SPADES, h=Suit.HEARTS, d=Suit.DIAMONDS, c=Suit.CLUBS)
        for text, expected in cases:
            cards = [Card(rank=Rank(c[0]), suit=suits[c[1]]) for c in text.split()]
            self.assertEqual(HandEvaluator().score(cards), expected)


class AnalysisCacheTests(unittest.TestCase):
    def test_cached_results_ignore_hidden_cards_but_are_detached_from_callers(self):
        engine = DecisionEngine()
        state = PokerEngine().start_hand()
        with patch.object(engine, '_analyze', wraps=engine._analyze) as calculate:
            first = engine.analyze(state)
            expected = first.model_dump()
            first.notes.append('Do not leak this mutation')
            first.hand_strength.cards.clear()
            state.players[1].cards.reverse()
            state._deck.reverse()
            second = engine.analyze(state)
            self.assertEqual(second.model_dump(), expected)
            self.assertEqual(calculate.call_count, 1)
            state.players[0].stack -= 1
            engine.analyze(state)
            self.assertEqual(calculate.call_count, 2)
            state.players[0].cards.reverse()
            engine.analyze(state)
            self.assertEqual(calculate.call_count, 3)

    def test_cache_is_bounded_and_distinguishes_players_and_histories(self):
        engine = DecisionEngine()
        engine.cache_capacity = 2
        poker = PokerEngine()
        state = poker.start_hand()
        with patch.object(engine, '_analyze', wraps=engine._analyze) as calculate:
            engine.analyze(state)
            engine.analyze(state, 'villain')
            following = poker.apply_action(state.model_copy(deep=True), 'hero', ActionType.CALL)
            engine.analyze(following)
            self.assertEqual(len(engine._analysis_cache), 2)
            engine.analyze(state)
            self.assertEqual(calculate.call_count, 4)

    def test_preflop_bot_uses_same_policy_without_equity_calculation(self):
        poker = PokerEngine()
        state = poker.apply_action(poker.start_hand(), 'hero', ActionType.CALL)
        full = DecisionEngine().analyze(state, 'villain')
        expected = AIOpponentService().choose_action(state, full)
        actual = AIOpponentService().choose_action(state, player_id='villain')
        self.assertEqual(actual, expected)
        with patch.object(api.decision_engine, 'analyze', side_effect=AssertionError('Unnecessary equity')):
            result = api._apply_ai_action_to_state(state, 'villain')
        self.assertEqual(result.history[-1].action, expected.action.value)


class AnalysisSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.old_state = api.current_state
        self.binding = api.training_owner.set(None)
        api.current_state = PokerEngine().start_hand()

    def tearDown(self):
        api.current_state = self.old_state
        api.training_owner.reset(self.binding)

    def test_slow_hint_does_not_hold_the_game_lock_or_observe_later_mutations(self):
        entered, release = Event(), Event()
        seen = []
        def slow_analysis(snapshot, player_id):
            seen.append(snapshot)
            entered.set()
            release.wait(timeout=5)
            return snapshot.hand_id
        original_length = len(api.current_state.history)
        with patch.object(api.decision_engine, 'analyze', side_effect=slow_analysis):
            with ThreadPoolExecutor(max_workers=2) as pool:
                hint = pool.submit(api.analyze_hand)
                try:
                    self.assertTrue(entered.wait(timeout=2))
                    action = pool.submit(api.apply_action, PlayerActionRequest(action=ActionType.CALL))
                    action.result(timeout=2)
                    self.assertGreater(len(api.current_state.history), original_length)
                    self.assertEqual(len(seen[0].history), original_length)
                finally:
                    release.set()
                hint.result(timeout=2)

    def test_expected_state_rejects_old_hand_history_and_street_before_calculation(self):
        state = api.current_state
        for values in [dict(hand_id='old'), dict(history_length=len(state.history) + 1), dict(street='flop')]:
            with patch.object(api.decision_engine, 'analyze') as calculate:
                with self.assertRaises(HTTPException) as caught:
                    api.analyze_hand(**values)
                self.assertEqual(caught.exception.status_code, 409)
                calculate.assert_not_called()
