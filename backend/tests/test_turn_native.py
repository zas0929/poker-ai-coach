import unittest
from unittest.mock import patch

from research.custom_river import demo_ranges
from research.native_cfr import load_library
from research.turn_native import compile_turn
from research.turn_reference import TurnGame

BOARD = ('2c', '4d', '7h', '9s')


class TurnNativeTests(unittest.TestCase):
    def test_compiler_preserves_masking_chance_slots_and_original_tree(self):
        game = TurnGame(BOARD, demo_ranges(2))
        nodes = tuple(game.nodes)
        slots = dict(game.utilities.slots)
        compiled = compile_turn(game)
        self.assertTrue(all(n.actor >= -1 for n in compiled.nodes))
        self.assertEqual(nodes, tuple(game.nodes))
        self.assertEqual(slots, game.utilities.slots)
        self.assertIs(game.utilities.data, compiled.utilities.data)
        self.assertEqual(len(compiled.keys), len(game.keys))
        self.assertAlmostEqual(sum(d[1] for d in compiled.deals), 1)
        a = next(d for d, (h, r, _, _) in enumerate(game.outcomes) if h == ('AhAd', 'KhKd') and r == '3c')
        b = next(d for d, (h, r, _, _) in enumerate(game.outcomes) if h == ('AhAd', 'KhKd') and r == '5c')
        self.assertEqual(compiled.key(compiled.root, a), compiled.key(compiled.root, b))
        river = compiled.root.children[0].children[0]
        self.assertNotEqual(compiled.key(river, a), compiled.key(river, b))

    def test_native_matches_python_on_two_street_private_uncertainty_and_all_seat_counts(self):
        try:
            load_library()
        except RuntimeError as error:
            self.skipTest(str(error))
        cases = [TurnGame(BOARD, demo_ranges(2), stack=8, turn_bet_sizes=(4,), river_bet_sizes=(4,))]
        for n in range(3, 7):
            cases.append(TurnGame(BOARD, [r[:1] for r in demo_ranges(n)], stack=2,
                                  turn_bet_sizes=(2,), river_bet_sizes=(2,)))
        cases.append(TurnGame(BOARD, [[(r[0][0], 1), ('8c8d', 1)] for r in demo_ranges(6)],
                              stack=2, turn_bet_sizes=(2,), river_bet_sizes=(2,)))
        for game in cases:
            reference = game.train(3)
            native = game.train(3, method='cfr_plus_native')
            self.assertEqual(set(reference), set(native))
            for key in reference:
                for a, b in zip(reference[key], native[key]):
                    self.assertAlmostEqual(a, b, places=11)
            a, b = game.measure(reference), game.measure(native)
            for metric in ('policy_payoffs', 'best_response_payoffs'):
                for x, y in zip(a[metric], b[metric]):
                    self.assertAlmostEqual(x, y, places=10)

    def test_empty_decision_tree_native_is_valid(self):
        try:
            load_library()
        except RuntimeError as error:
            self.skipTest(str(error))
        game = TurnGame(BOARD, demo_ranges(2), stack=0)
        self.assertEqual(game.train(2, method='cfr_plus_native'), {})

    def test_compiler_refuses_over_budget_before_calling_numeric_kernel(self):
        game = TurnGame(BOARD, demo_ranges(2))
        with patch.object(game, 'outcomes', game.outcomes * 2000):
            with self.assertRaisesRegex(ValueError, 'budget'):
                compile_turn(game)

    def test_unknown_training_method_rejected(self):
        game = TurnGame(BOARD, demo_ranges(2))
        with self.assertRaises(ValueError):
            game.train(1, method='river_native_direct')
