import math
from types import SimpleNamespace
import unittest

from research.custom_river import RiverGame, Node
from research.deal_sampling import sample_joint_ranges, SampleView
from research.fixed_deviation import (fit_responses, deal_payoffs, paired_intervals,
                                      evaluate_fixed_deviations)
from research.fused_best_response import evaluate_policy

BOARD = ['2c', '4d', '7h', '9s', 'Jc']


class FixedDeviationTests(unittest.TestCase):
    def setUp(self):
        self.game = RiverGame(BOARD, [[('AhAd', 1.), ('QhQd', 3.)], [('KhKd', 1.)]],
                              bet_sizes=[10], utility_storage='compact')
        self.policy = {key: [1./c] * c for key, c in self.game.action_counts.items()}

    def draw(self, seed, samples=64):
        return sample_joint_ranges(BOARD, self.game.ranges, samples=samples, seed=seed, max_attempts=10000)

    def test_extracted_responses_match_fit_best_response_without_hidden_card_peeking(self):
        leaves = [Node(-1, ('a',)), Node(-1, ('b',))]
        root = Node(0, (), ('a', 'b'), tuple(leaves))
        game = SimpleNamespace(n=2, root=root, nodes=[root, *leaves], decision_pot=1.,
            deals=[(('AhAd', 'KhKd'), .5, None), (('AhAd', 'QhQd'), .5, None)])
        key = (0, 'AhAd', ())
        game.keys = {key}
        game.action_counts = {key: 2}
        game.key = lambda node, d: (node.actor, game.deals[d][0][node.actor], node.history)
        # A clairvoyant responder gets 1; a legal response gets only .5.
        game.utilities = {(id(leaf), d): (float(a == d), -float(a == d))
                          for a, leaf in enumerate(leaves) for d in range(2)}
        draw = {'status': 'sampled', 'counts': {t: 1 for t, _, _ in game.deals}, 'requested': 2, 'seed': 73}
        fitted = fit_responses(game, {key: [.5, .5]}, draw)
        self.assertEqual(fitted['responses'][0][key], [1., 0.])
        values = deal_payoffs(game, {key: [.5, .5]}, fitted['responses'])
        candidate = sum(w * v[1][0] for (_, w, _), v in zip(game.deals, values))
        self.assertEqual(candidate, .5)
        self.assertEqual(candidate, fitted['fit_metrics']['best_response_payoffs'][0])

    def test_joint_deviation_traversal_matches_separate_profile_evaluations(self):
        fitted = fit_responses(self.game, self.policy, self.draw(73))
        values = deal_payoffs(self.game, self.policy, fitted['responses'])
        reference, _ = evaluate_policy(self.game, self.policy)
        for p in range(self.game.n):
            changed = {k: list(v) for k, v in self.policy.items()}
            changed.update(fitted['responses'][p])
            exact, _ = evaluate_policy(self.game, changed)
            profile_value = sum(w*v[0][p] for (_, w, _), v in zip(self.game.deals, values))
            candidate_value = sum(w*v[1][p] for (_, w, _), v in zip(self.game.deals, values))
            self.assertAlmostEqual(profile_value, reference['policy_payoffs'][p])
            self.assertAlmostEqual(candidate_value, exact['policy_payoffs'][p])
            self.assertLessEqual(candidate_value, reference['best_response_payoffs'][p] + 1e-9)

    def test_missing_fit_rows_preserve_base_policy_and_testing_does_not_refit(self):
        fitted = fit_responses(self.game, self.policy, self.draw(73, 1))
        view = SampleView(self.game, self.draw(73, 1))
        self.assertGreater(fitted['fit_missing_rows'], 0)
        for key in view.missing_keys:
            self.assertEqual(fitted['responses'][key[0]][key], self.policy[key])
        hashes = list(fitted['response_sha256'])
        result = evaluate_fixed_deviations(self.game, self.policy, fitted, self.draw(4001), delta=.05)
        self.assertEqual(hashes, fitted['response_sha256'])
        self.assertFalse(result['quality_pass_allowed'])
        self.assertFalse(result['live_advice_allowed'])

    def test_reused_fit_seed_and_changed_policies_or_responses_are_refused(self):
        fitted = fit_responses(self.game, self.policy, self.draw(73))
        with self.assertRaises(ValueError):
            evaluate_fixed_deviations(self.game, self.policy, fitted, self.draw(73), delta=.05)
        key = next(iter(self.policy))
        altered = dict(self.policy)
        altered[key] = [float(i == 0) for i in range(len(altered[key]))]
        with self.assertRaises(ValueError):
            evaluate_fixed_deviations(self.game, altered, fitted, self.draw(4001), delta=.05)
        key = next(iter(fitted['responses'][0]))
        row = fitted['responses'][0][key]
        fitted['responses'][0][key] = [1. / len(row)] * len(row)
        with self.assertRaises(ValueError):
            evaluate_fixed_deviations(self.game, self.policy, fitted, self.draw(4001), delta=.05)

    def test_pairing_removes_common_noise_but_not_confidence_penalty(self):
        values = [([100.], [101.]), ([200.], [201.])]
        row = paired_intervals(values, [2048, 2048], [101.], .05)[0]
        self.assertEqual(row['sample_variance'], 0.)
        self.assertGreater(row['independent_difference_variance'], 0.)
        self.assertEqual(row['mean_difference_chips'], 1.)
        self.assertGreater(row['bernstein_radius_chips'], 0.)
        self.assertLess(row['bernstein_radius_chips'], row['hoeffding_radius_chips'])
        negative = paired_intervals([([2.], [1.]), ([4.], [3.])], [2048, 2048], [3.], .05)[0]
        self.assertEqual(negative['mean_difference_chips'], -1.)
        self.assertLess(negative['interval_chips'][1], 0.)
        with self.assertRaises(ValueError):
            paired_intervals(values[:1], [1], [101.], .05)

    def test_combined_interval_against_exact_binomial_probability(self):
        samples = 128
        delta = .1
        failure = 0.
        for heads in range(samples+1):
            pairs = [([0.], [-1.]), ([0.], [1.])]
            kept = [(pair, c) for pair, c in zip(pairs, [samples-heads, heads]) if c]
            row = paired_intervals([pair for pair, _ in kept], [c for _, c in kept], [1.], delta)[0]
            if not row['interval_chips'][0] <= 0. <= row['interval_chips'][1]:
                failure += math.comb(samples, heads) / 2**samples
        self.assertLessEqual(failure, delta)

    def test_clear_poker_blunder_can_be_confirmed_without_ever_allowing_quality_pass(self):
        # Development positive control: always check/fold instead of training.
        bad = {key: [float(a == 0) for a in range(c)] for key, c in self.game.action_counts.items()}
        fitted = fit_responses(self.game, bad, self.draw(73))
        result = evaluate_fixed_deviations(self.game, bad, fitted, self.draw(4001, 8192), delta=.01)
        exact, _ = evaluate_policy(self.game, bad)
        self.assertGreater(exact['max_unilateral_gain_pct_pot'], .5)
        self.assertTrue(result['confirms_above_threshold'])
        self.assertFalse(result['quality_pass_allowed'])
        self.assertFalse(result['live_advice_allowed'])
