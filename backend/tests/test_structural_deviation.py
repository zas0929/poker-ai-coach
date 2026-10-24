import unittest

from research.custom_river import RiverGame
from research.deal_sampling import sample_joint_ranges
from research.fixed_deviation import fit_responses, deal_payoffs
from research.independent_evaluation import payoff_bounds
from research.structural_deviation import (terminal_envelopes, response_envelopes,
    prepare_envelopes, signed_intervals, evaluate_structural)

BOARD = ['2c', '4d', '7h', '9s', 'Jc']


class StructuralDeviationTests(unittest.TestCase):
    def setUp(self):
        self.game = RiverGame(BOARD, [[('AhAd', 1.), ('QhQd', 3.)], [('KhKd', 1.), ('KcKs', 2.)]],
                              bet_sizes=[10], raise_sizes=[20], max_raises=1, utility_storage='compact')
        self.policy = {key: [1./c] * c for key, c in self.game.action_counts.items()}

    def draw(self, seed):
        return sample_joint_ranges(BOARD, self.game.ranges, samples=128, seed=seed, max_attempts=10000)

    def test_unchanged_responses_are_zero_without_accessing_deals_or_utilities(self):
        responses = [{k: list(v) for k, v in self.policy.items() if k[0] == p} for p in range(self.game.n)]
        deals, utilities = self.game.deals, self.game.utilities
        self.game.deals = object()
        self.game.utilities = object()
        bounds = response_envelopes(self.game, self.policy, responses)
        self.game.deals, self.game.utilities = deals, utilities
        self.assertTrue(all(p['bounds_chips'] == [0., 0.] for p in bounds))

    def test_rank_extremes_cover_sidepots_refunds_folds_and_board_ties(self):
        sidepot = RiverGame(BOARD, [[('AhAd', 1.)], [('KhKd', 1.)], [('ThTd', 1.)], []],
            pot=140, initial_contributions=[20, 40, 40, 40], stacks=[0, 20, 40, 0],
            folded=[3], bet_sizes=[10], raise_sizes=[20], max_raises=1)
        tied = RiverGame(['Ts', 'Js', 'Qs', 'Ks', 'As'], [[('AhAd', 1.)], [('KhKd', 1.)]],
            pot=10, initial_contributions=[5, 5], stacks=[0, 0], bet_sizes=[1])
        for game in (sidepot, tied):
            envelopes = terminal_envelopes(game)
            for node in game.nodes:
                if node.actor != -1:
                    continue
                for d in range(len(game.deals)):
                    for value, (lo, hi) in zip(game.utilities[(id(node), d)], envelopes[id(node)]):
                        self.assertLessEqual(lo, value)
                        self.assertGreaterEqual(hi, value)

    def test_public_envelopes_cover_every_exact_deal_and_own_hand(self):
        fitted = fit_responses(self.game, self.policy, self.draw(73))
        envelopes = response_envelopes(self.game, self.policy, fitted['responses'])
        values = deal_payoffs(self.game, self.policy, fitted['responses'])
        for (texts, _, _), (base, dev) in zip(self.game.deals, values):
            for p, row in enumerate(envelopes):
                lo, hi = row['own_hand_bounds'][texts[p]]
                self.assertLessEqual(lo-1e-8, dev[p]-base[p])
                self.assertGreaterEqual(hi+1e-8, dev[p]-base[p])

    def test_small_policy_change_has_tighter_structural_range(self):
        pure = {k: [float(i == 0) for i in range(c)] for k, c in self.game.action_counts.items()}
        responses = []
        for p in range(self.game.n):
            response = {}
            for key, row in pure.items():
                if key[0] == p:
                    response[key] = [v*.99 + .01/len(row) for v in row]
            responses.append(response)
        envelopes = response_envelopes(self.game, pure, responses)
        generic = [hi-lo for lo, hi in payoff_bounds(self.game)]
        self.assertTrue(all(row['bounds_chips'][1]-row['bounds_chips'][0] < 2*r
                            for row, r in zip(envelopes, generic)))
        values = deal_payoffs(self.game, pure, responses)
        for base, dev in values:
            for p, row in enumerate(envelopes):
                self.assertLessEqual(row['bounds_chips'][0]-1e-8, dev[p]-base[p])
                self.assertGreaterEqual(row['bounds_chips'][1]+1e-8, dev[p]-base[p])

    def test_frozen_evaluation_never_admits_quality_and_intervals_do_not_widen(self):
        fitted = fit_responses(self.game, self.policy, self.draw(73))
        generic = [hi-lo for lo, hi in payoff_bounds(self.game)]
        prepared = prepare_envelopes(self.game, self.policy, fitted, generic)
        result = evaluate_structural(self.game, self.policy, fitted, prepared, self.draw(1237), delta=.01)
        for row in result['players']:
            lo, hi = row['interval_chips']
            old_lo, old_hi = row['previous_interval_chips']
            self.assertLessEqual(old_lo-1e-8, lo)
            self.assertGreaterEqual(old_hi+1e-8, hi)
        self.assertFalse(result['quality_pass_allowed'])
        self.assertFalse(result['live_advice_allowed'])
        with self.assertRaises(ValueError):
            evaluate_structural(self.game, self.policy, fitted, prepared, self.draw(73), delta=.01)

    def test_signed_bounds_validate_samples_and_keep_constant_intervals_ordered(self):
        rows = signed_intervals([([10.], [10. + 1e-12])], [8], [(0., 0.)], .05)
        self.assertEqual(rows[0]['interval_chips'], [0., 0.])
        with self.assertRaises(ValueError):
            signed_intervals([([1.], [3.])], [8], [(-1., 1.)], .05)
