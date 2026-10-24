import math
from types import SimpleNamespace
import unittest

from research.custom_river import RiverGame
from research.deal_sampling import SampleView, sample_joint_ranges
from research.fused_best_response import evaluate_policy
from research.independent_evaluation import confidence_envelope, evaluate_independent, payoff_bounds

BOARD = ['2c', '4d', '7h', '9s', 'Jc']


class IndependentEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.game = RiverGame(BOARD, [[('AhAd', 1.), ('QhQd', 3.)], [('KhKd', 1.)]],
                              bet_sizes=[10], utility_storage='compact')
        self.policy = {key: [1. / count] * count for key, count in self.game.action_counts.items()}

    def draw(self, samples=1):
        return sample_joint_ranges(BOARD, self.game.ranges, samples=samples, seed=1009, max_attempts=10000)

    def test_missing_evaluation_hands_do_not_require_invented_policy_rows(self):
        draw = self.draw()
        before = {key: list(row) for key, row in self.policy.items()}
        result = evaluate_independent(self.game, self.policy, draw, delta=.05)
        self.assertGreater(result['evaluation_missing_rows'], 0)
        self.assertEqual(self.policy, before)
        view = SampleView(self.game, draw)
        empirical, _ = evaluate_policy(view, {k: self.policy[k] for k in view.keys})
        self.assertEqual(result['metrics'], empirical)
        # Confidence complexity includes unseen original hands as well.
        for p, row in enumerate(result['confidence']['players']):
            expected = math.fsum(math.log(c) for key, c in self.game.action_counts.items() if key[0] == p)
            self.assertEqual(row['log_pure_response_count'], expected)
        self.assertFalse(result['live_advice_allowed'])

    def test_partial_training_policy_and_incomplete_draw_refused(self):
        incomplete = dict(self.policy)
        incomplete.pop(next(iter(incomplete)))
        with self.assertRaises(ValueError):
            evaluate_independent(self.game, incomplete, self.draw(), delta=.05)
        draw = self.draw()
        draw['status'] = 'proposal_budget_exhausted'
        with self.assertRaises(ValueError):
            evaluate_independent(self.game, self.policy, draw, delta=.05)
        for delta in (0, 1, float('nan'), True):
            with self.assertRaises(ValueError):
                evaluate_independent(self.game, self.policy, self.draw(), delta=delta)

    def test_more_draws_narrow_bounds_and_more_responses_widen_them(self):
        game = SimpleNamespace(n=2, decision_pot=10., action_counts={(0, 'a'): 2, (1, 'b'): 2})
        metrics = {'policy_payoffs': [5., 5.], 'best_response_payoffs': [6., 6.]}
        small = confidence_envelope(game, metrics, 128, .05, [(0., 10.)] * 2)
        large = confidence_envelope(game, metrics, 2048, .05, [(0., 10.)] * 2)
        self.assertGreater(small['max_gain_upper_pct_pot'], large['max_gain_upper_pct_pot'])
        game.action_counts[(0, 'unseen')] = 1000
        complex_bound = confidence_envelope(game, metrics, 2048, .05, [(0., 10.)] * 2)
        self.assertGreater(complex_bound['players'][0]['response_radius_chips'], large['players'][0]['response_radius_chips'])
        self.assertEqual(complex_bound['players'][0]['policy_radius_chips'], large['players'][0]['policy_radius_chips'])

    def test_finite_response_bound_against_exhaustive_binomial_law(self):
        # Hidden fair bit; two pure responses pay bit / (1-bit). Choosing the
        # larger sample mean creates optimism despite a fixed opponent policy.
        game = SimpleNamespace(n=2, decision_pot=1., action_counts={(0, 'h'): 2})
        samples = 128
        delta = .1
        failure_probability = 0.
        expected_empirical_response = 0.
        for heads in range(samples + 1):
            p = heads / samples
            mass = math.comb(samples, heads) / 2 ** samples
            response = max(p, 1-p)
            metrics = {'policy_payoffs': [.5, 0.], 'best_response_payoffs': [response, 0.]}
            result = confidence_envelope(game, metrics, samples, delta, [(0., 1.), (0., 0.)])
            row = result['players'][0]
            if not (row['policy_interval_chips'][0] <= .5 <= row['policy_interval_chips'][1]
                    and row['response_interval_chips'][0] <= .5 <= row['response_interval_chips'][1]
                    and row['gain_interval_chips'][0] <= 0 <= row['gain_interval_chips'][1]):
                failure_probability += mass
            expected_empirical_response += mass * response
        self.assertGreater(expected_empirical_response, .5)
        self.assertLessEqual(failure_probability, delta)

    def test_terminal_bounds_cover_exact_values_and_sample_envelopes(self):
        exact, _ = evaluate_policy(self.game, self.policy)
        bounds = payoff_bounds(self.game)
        result = evaluate_independent(self.game, self.policy, self.draw(), delta=.01)
        for p, row in enumerate(result['confidence']['players']):
            self.assertLessEqual(bounds[p][0], exact['policy_payoffs'][p])
            self.assertGreaterEqual(bounds[p][1], exact['best_response_payoffs'][p])
            lo, hi = row['gain_interval_chips']
            self.assertLessEqual(lo, exact['unilateral_gains'][p] + 1e-9)
            self.assertGreaterEqual(hi + 1e-9, exact['unilateral_gains'][p])
