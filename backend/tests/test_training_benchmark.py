import unittest
from research.benchmark_training import scenarios, TARGET_MAX_GAIN_PCT_POT
from research.custom_river import RiverGame

class TrainingBenchmarkTests(unittest.TestCase):
    def test_fixed_suite_covers_all_player_counts_and_textures_repeatably(self):
        first=list(scenarios())
        self.assertEqual(first,list(scenarios()))
        self.assertEqual(len(first),20)
        self.assertEqual({n for _,n,*_ in first},set(range(2,7)))
        self.assertEqual({name for name,*_ in first},{'original_dry','weighted_flush','weighted_paired','board_tie'})
        self.assertEqual(TARGET_MAX_GAIN_PCT_POT,.5)
        for _,n,board,ranges,pot,bet in first:
            game=RiverGame(board,ranges,pot=pot,bet=bet,stack=100)
            self.assertEqual(game.n,n)
            self.assertGreater(len(game.deals),0)
