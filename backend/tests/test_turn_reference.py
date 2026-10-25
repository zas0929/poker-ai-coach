import math
import unittest
from collections import defaultdict

from research.custom_river import demo_ranges
from research.turn_oracle import compare_every_path
from research.turn_reference import DECK, REVEAL, TERMINAL, TurnGame

BOARD = ('2c', '4d', '7h', '9s')


def follow(game, *labels):
    node = game.root
    for label in labels:
        node = node.children[node.actions.index(label)]
    return node


class TurnReferenceTests(unittest.TestCase):
    def game(self, n=2, **kwargs):
        return TurnGame(BOARD, demo_ranges(n), **kwargs)

    def test_joint_chance_conditions_on_all_private_cards_and_normalizes(self):
        g = TurnGame(BOARD, [[('AhAd', 3), ('QhQd', 1)], [('AhAd', 2), ('KhKd', 1)]])
        private = defaultdict(float)
        rivers = defaultdict(set)
        for hands, river, weight, _ in g.outcomes:
            private[hands] += weight
            rivers[hands].add(river)
            self.assertNotIn(river, BOARD)
            self.assertNotIn(river, [h[i:i+2] for h in hands for i in (0, 2)])
        self.assertEqual(g.joint_private_deals, 3)
        self.assertAlmostEqual(sum(private.values()), 1)
        self.assertAlmostEqual(private[('AhAd', 'KhKd')], 3/6)
        self.assertAlmostEqual(private[('QhQd', 'AhAd')], 2/6)
        self.assertAlmostEqual(private[('QhQd', 'KhKd')], 1/6)
        self.assertTrue(all(len(row) == 44 for row in rivers.values()))
        # Kc is blocked only in the lineups containing KK.
        self.assertIn('Kc', rivers[('QhQd', 'AhAd')])
        self.assertNotIn('Kh', rivers[('QhQd', 'KhKd')])
        self.assertNotIn('Ah', rivers[('QhQd', 'AhAd')])

    def test_future_river_is_hidden_until_public_reveal_and_other_hands_stay_hidden(self):
        g = self.game()
        a = next(d for d, (h, r, _, _) in enumerate(g.outcomes) if h == ('AhAd', 'KhKd') and r == '3c')
        b = next(d for d, (h, r, _, _) in enumerate(g.outcomes) if h == ('AhAd', 'KhKd') and r == '5c')
        c = next(d for d, (h, r, _, _) in enumerate(g.outcomes) if h == ('AhAd', '5h5d') and r == '3c')
        self.assertEqual(g.key(g.root, a), g.key(g.root, b))
        self.assertEqual(g.key(g.root, a), g.key(g.root, c))
        reveal = follow(g, 'CHECK', 'CHECK')
        self.assertEqual(reveal.actor, REVEAL)
        river = reveal.children[0]
        self.assertNotEqual(g.key(river, a), g.key(river, b))
        self.assertEqual(g.key(river, a), g.key(river, c))
        self.assertEqual(g.key(river, a)[-1], '3c')

    def test_best_response_cannot_choose_turn_action_after_seeing_future_river(self):
        g = TurnGame(BOARD, [[('AhAd', 1)], [('KhKd', 1)]], pot=100, stack=20,
                     turn_bet_sizes=(10,), river_bet_sizes=())
        policy = {}
        for node in g.nodes:
            if node.actor < 0:
                continue
            row = [0.] * len(node.actions)
            row[node.actions.index('CALL') if 'CALL' in node.actions else node.actions.index('CHECK')] = 1
            for deal in range(len(g.outcomes)):
                policy[g.key(node, deal)] = row
        checked = follow(g, 'CHECK', 'CHECK', 'REVEAL_RIVER', 'CHECK', 'CHECK')
        wagered = follow(g, 'BET 10', 'CALL', 'REVEAL_RIVER', 'CHECK', 'CHECK')
        check_ev = bet_ev = clairvoyant = 0.
        for d, (_, _, w, _) in enumerate(g.outcomes):
            c, b = (g.utilities[(id(node), d)][0] for node in (checked, wagered))
            check_ev += w*c
            bet_ev += w*b
            clairvoyant += w*max(c, b)
        actual = g.measure(policy)['best_response_payoffs'][0]
        self.assertAlmostEqual(actual, max(check_ev, bet_ev))
        self.assertGreater(clairvoyant, actual + .1)

    def test_river_best_response_can_adapt_after_card_is_public(self):
        g = TurnGame(BOARD, [[('AhAd', 1)], [('KhKd', 1)]], pot=100, stack=20,
                     turn_bet_sizes=(), river_bet_sizes=(10,))
        policy = {}
        for node in g.nodes:
            if node.actor < 0:
                continue
            row = [0.] * len(node.actions)
            row[node.actions.index('CALL') if 'CALL' in node.actions else node.actions.index('CHECK')] = 1
            for d in range(len(g.outcomes)):
                policy[g.key(node, d)] = row
        checked = follow(g, 'CHECK', 'CHECK', 'REVEAL_RIVER', 'CHECK', 'CHECK')
        wagered = follow(g, 'CHECK', 'CHECK', 'REVEAL_RIVER', 'BET 10', 'CALL')
        oracle = sum(w * max(g.utilities[(id(checked), d)][0], g.utilities[(id(wagered), d)][0])
                     for d, (_, _, w, _) in enumerate(g.outcomes))
        self.assertAlmostEqual(g.measure(policy)['best_response_payoffs'][0], oracle)

    def test_all_outcomes_and_branches_match_engine_two_and_three_seats(self):
        for n in (2, 3):
            g = TurnGame(BOARD, [r[:1] for r in demo_ranges(n)], pot=20*n,
                         initial_contributions=(20,)*n, stacks=(5, 10, 15)[:n], min_bet=2,
                         turn_bet_sizes=(10,), river_bet_sizes=(10,))
            result = compare_every_path(g)
            self.assertEqual(result['outcomes_verified'], len(g.outcomes))
            self.assertGreater(result['terminal_outcome_checks'], len(g.outcomes))

    def test_all_paths_representative_runouts_match_engine_four_to_six_seats(self):
        for n in (4, 5, 6):
            g = TurnGame(BOARD, [r[:1] for r in demo_ranges(n)], pot=20*n,
                         initial_contributions=(20,)*n, stacks=(5, 10, 15, 20, 25, 30)[:n],
                         min_bet=2, turn_bet_sizes=(10,), river_bet_sizes=(10,))
            self.assertGreater(compare_every_path(g, (0, len(g.outcomes)-1))['terminal_outcome_checks'], 0)
            self.assertTrue(all(abs(sum(values)) < 1e-8 for values in g.utilities.values()))

    def test_prior_side_pots_folded_dead_money_short_bets_and_uncalled_returns(self):
        for kwargs, ranges in (
                ({'stacks': (0, 8, 30), 'pot': 50, 'initial_contributions': (10, 20, 20)},
                 [r[:1] for r in demo_ranges(3)]),
                ({'stacks': (8, 30, 100), 'pot': 60, 'initial_contributions': (20, 20, 20), 'folded': (2,)},
                 [[('AhAd', 1)], [('KhKd', 1)], []]),
                ({'stacks': (3, 5), 'pot': 40, 'initial_contributions': (20, 20)},
                 [r[:1] for r in demo_ranges(2)])):
            g = TurnGame(BOARD, ranges, min_bet=5, turn_bet_sizes=(10,), river_bet_sizes=(10,), **kwargs)
            compare_every_path(g)
        # A turn all-in excess is returned before the public reveal.
        g = TurnGame(BOARD, [[('AhAd', 1)], [('KhKd', 1)]], stacks=(30, 5),
                     turn_bet_sizes=(10,), river_bet_sizes=(10,))
        reveal = follow(g, 'BET 10', 'CALL')
        self.assertEqual(reveal.invested, (5, 5))
        self.assertEqual(reveal.children[0].actor, TERMINAL)

    def test_folded_during_turn_cards_still_block_river(self):
        g = TurnGame(BOARD, [r[:1] for r in demo_ranges(3)], pot=60, stack=30,
                     turn_bet_sizes=(10,), river_bet_sizes=(10,))
        reveal = follow(g, 'BET 10', 'FOLD', 'CALL')
        self.assertEqual(reveal.alive, (0, 2))
        self.assertTrue(all(r not in ('Kh', 'Kd') for _, r, _, _ in g.outcomes))

    def test_odd_chips_allin_and_public_board_ties_match_engine(self):
        g = TurnGame(('As', 'Ks', 'Qs', 'Js'), [[('2h2d', 1)], [('3h3d', 1)], [('4h4d', 1)]],
                     pot=5, stacks=(0, 0, 0), initial_contributions=(2, 1, 2), dealer=1)
        compare_every_path(g)
        deal = next(d for d, (_, r, _, _) in enumerate(g.outcomes) if r == 'Ts')
        terminal = g.root.children[0]
        self.assertEqual(g.settle(terminal, g.outcomes[deal][3])[0], (2, 1, 2))
        self.assertEqual(g.train(3), {})
        self.assertAlmostEqual(sum(g.measure({})['policy_payoffs']), 0)

    def test_learning_reduces_exact_gap_and_policies_repeat(self):
        g = TurnGame(BOARD, [[('AhAd', 1)], [('KhKd', 1)]], pot=40,
                     stack=20, turn_bet_sizes=(10,), river_bet_sizes=(10,))
        before = g.measure(g.uniform_policy())
        policy = g.train(60)
        after = g.measure(policy)
        self.assertLess(after['nash_conv_chips'], before['nash_conv_chips']/10)
        self.assertAlmostEqual(sum(after['policy_payoffs']), 0)
        self.assertEqual(policy, g.train(60))
        for row in policy.values():
            self.assertAlmostEqual(sum(row), 1)
            self.assertTrue(all(math.isfinite(v) and 0 <= v <= 1 for v in row))

    def test_multiple_sizes_and_training_for_one_to_five_opponents(self):
        for n in range(2, 7):
            # Two bet sizes on each street; small remaining stacks can dedupe sizes.
            g = TurnGame(BOARD, [r[:1] for r in demo_ranges(n)], pot=20*n, stack=2,
                         initial_contributions=(20,)*n, min_bet=2,
                         turn_bet_sizes=(2, 5), river_bet_sizes=(2, 5))
            policy = g.train(1)
            self.assertEqual(set(policy), g.keys)
            self.assertAlmostEqual(sum(g.measure(policy)['policy_payoffs']), 0)
        g = TurnGame(BOARD, demo_ranges(2), stack=5, min_bet=2,
                     turn_bet_sizes=(2, 5), river_bet_sizes=(2, 5))
        self.assertEqual(g.root.actions, ('CHECK', 'BET 2', 'BET 5'))
        compare_every_path(TurnGame(BOARD, [r[:1] for r in demo_ranges(2)], stack=5,
                                   pot=40, initial_contributions=(20, 20), min_bet=2,
                                   turn_bet_sizes=(2, 5), river_bet_sizes=(2, 5)))

    def test_root_action_values_average_hidden_outcomes_and_keep_fixed_continuation(self):
        g = self.game(stack=20, turn_bet_sizes=(10,), river_bet_sizes=(10,))
        policy = g.uniform_policy()
        metrics = g.measure(policy)
        rows = [g.root_action_values(policy, hand) for hand, _ in g.ranges[g.root.actor]]
        average = sum(row['conditional_mass'] * row['policy_ev_chips'] for row in rows)
        self.assertAlmostEqual(average, metrics['policy_payoffs'][g.root.actor]
                               + g.initial_contributions[g.root.actor])
        for row in rows:
            self.assertAlmostEqual(sum(a['probability'] for a in row['actions']), 1)
            best = max(a['ev_chips'] for a in row['actions'])
            for a in row['actions']:
                self.assertAlmostEqual(a['gap_to_best_first_action_chips'], best - a['ev_chips'])
        with self.assertRaises(ValueError):
            g.root_action_values(policy, 'AsKs')
        with self.assertRaises(ValueError):
            g.root_action_values({}, 'AhAd')

    def test_rejects_invalid_input_and_budgets_without_truncation(self):
        bads = ({'pot': True}, {'min_bet': 0}, {'stacks': (1,)}, {'stacks': (True, 1)},
                {'dealer': 2}, {'folded': (0,)}, {'turn_bet_sizes': (0,)},
                {'turn_bet_sizes': (10, 10)}, {'river_bet_sizes': (1, 2, 3)},
                {'initial_contributions': (1, 2)}, {'max_joint_combos': 1},
                {'max_nodes': 1}, {'max_outcomes': 1}, {'max_work': 1})
        for kwargs in bads:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.game(**kwargs)
        for board, ranges in ((BOARD[:3], demo_ranges(2)), (('2c',)*4, demo_ranges(2)),
                              (BOARD, [[('AhAh', 1)], [('KhKd', 1)]]),
                              (BOARD, [[('2cAh', 1)], [('KhKd', 1)]]),
                              (BOARD, [[('AhAd', 1)], [('AdAh', 1)]]),
                              (BOARD, [[('AhAd', float('nan'))], [('KhKd', 1)]])):
            with self.assertRaises(ValueError):
                TurnGame(board, ranges)
        g = self.game()
        with self.assertRaises(ValueError):
            g.train(1, max_visits=1)
        for iterations in (True, 0, 2001, 1.5):
            with self.assertRaises(ValueError):
                g.train(iterations)
        for policy in ({}, {k: [float('nan')]*m for k, m in g.action_counts.items()}):
            with self.assertRaises(ValueError):
                g.measure(policy)

    def test_best_response_cannot_peek_at_opponents_even_after_future_card_grouping(self):
        g = TurnGame(BOARD, [[('AhAd', 1), ('QhQd', 1)], [('KhKd', 1)]],
                     stack=20, turn_bet_sizes=(10,), river_bet_sizes=())
        policy = {}
        for node in g.nodes:
            if node.actor < 0:
                continue
            label = 'BET 10' if node is g.root else ('CALL' if 'CALL' in node.actions else 'CHECK')
            row = [float(a == label) for a in node.actions]
            for d in range(len(g.outcomes)):
                policy[g.key(node, d)] = row
        folded = follow(g, 'BET 10', 'FOLD')
        called = follow(g, 'BET 10', 'CALL', 'REVEAL_RIVER', 'CHECK', 'CHECK')
        fold_ev = call_ev = clairvoyant = 0.
        for d, (_, _, w, _) in enumerate(g.outcomes):
            f, c = (g.utilities[(id(node), d)][1] for node in (folded, called))
            fold_ev += w*f
            call_ev += w*c
            clairvoyant += w*max(f, c)
        actual = g.measure(policy)['best_response_payoffs'][1]
        self.assertAlmostEqual(actual, max(fold_ev, call_ev))
        self.assertGreater(clairvoyant, actual + .1)

    def test_deck_and_terminal_only_public_reveal_are_complete(self):
        self.assertEqual(len(set(DECK)), 52)
        g = self.game(stack=0)
        self.assertEqual(g.root.actor, REVEAL)
        self.assertEqual(g.root.children[0].actor, TERMINAL)
        self.assertEqual(len(g.outcomes), 4*44)
        self.assertEqual(g.measure({})['nash_conv_chips'], 0)
