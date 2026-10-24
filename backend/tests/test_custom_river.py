import unittest
from research.custom_river import RiverGame, demo_ranges

BOARD=['2c','4d','7h','9s','Jc']
class CustomRiverTests(unittest.TestCase):
    def test_two_to_six_players_have_zero_sum_payoffs_and_valid_strategies(self):
        for n in range(2,7):
            game=RiverGame(BOARD,[r[:1] for r in demo_ranges(n)])
            policy=game.train(4)
            for row in policy.values():
                self.assertAlmostEqual(sum(row),1)
                self.assertTrue(all(0<=p<=1 for p in row))
            for values in game.utilities.values():self.assertAlmostEqual(sum(values),0)
            self.assertEqual(len(game.ranges),n)
            self.assertTrue(all(len(k)==3 for k in game.keys))

    def test_learning_reduces_exact_best_response_gap_on_two_player_control(self):
        game=RiverGame(BOARD,demo_ranges(2))
        before=game.measure({k:[.5,.5] for k in game.keys})
        after=game.measure(game.train(300))
        self.assertLess(after['nash_conv_chips'],before['nash_conv_chips']/10)
        self.assertAlmostEqual(sum(after['policy_payoffs']),0)

    def test_identical_board_winner_control_is_not_hand_ranking_guess(self):
        game=RiverGame(['As','Ks','Qs','Js','Ts'],[[('2h2d',1)],[('3h3d',1)]])
        result=game.measure(game.train(300))
        self.assertLess(result['nash_conv_chips'],1)

    def test_best_response_does_not_peek_at_opponents_private_cards(self):
        game=RiverGame(BOARD,[[('AhAd',1),('QhQd',1)],[('KhKd',1)]])
        policy={}
        for key in game.keys:
            actor,_,history=key
            policy[key]=[0,1] if not history else ([.5,.5] if history==((0,'BET 50'),) else [1,0])
        result=game.measure(policy)
        # IP cannot choose a different call/fold for AA and QQ: its cards/history match.
        self.assertAlmostEqual(result['best_response_payoffs'][1],0)
        self.assertAlmostEqual(result['policy_payoffs'][1],-25)

    def test_colliding_ranges_and_oversized_games_are_rejected(self):
        for ranges in ([[('AhAh',1)],[('KhKd',1)]],[[('2cAh',1)],[('KhKd',1)]],[[('AhAd',1)],[('AdAh',1)]],[[('AhAd',float('nan'))],[('KhKd',1)]]):
            with self.assertRaises(ValueError):RiverGame(BOARD,ranges)
        with self.assertRaises(ValueError):RiverGame(BOARD,[r*3 for r in demo_ranges(6)])

    def test_chance_is_jointly_conditioned_on_card_collisions(self):
        game=RiverGame(BOARD,[[('AhAd',1),('QhQd',1)],[('AhAd',1),('KhKd',1)]])
        self.assertEqual(len(game.deals),3)
        self.assertTrue(all(abs(weight-1/3)<1e-9 for _,weight,_ in game.deals))

    def test_external_tree_conversion_refuses_nonmatching_action_sets(self):
        from research.compare_custom_policy import convert_policy
        game=RiverGame(BOARD,demo_ranges(2))
        with self.assertRaises(ValueError):convert_policy(game,{'player':1,'actions':['CHECK','BET 100.000000']})

    def test_invalid_card_notations_and_policies_are_rejected(self):
        for ranges in ([[('AhXx',1)],[('KhKd',1)]],[[('A',1)],[('KhKd',1)]]):
            with self.assertRaises(ValueError):RiverGame(BOARD,ranges)
        game=RiverGame(BOARD,demo_ranges(2))
        with self.assertRaises(ValueError):game.measure({})

    def test_external_rows_are_reordered_and_float32_roundoff_normalized(self):
        from research.compare_custom_policy import convert_policy
        game=RiverGame(BOARD,demo_ranges(2),stack=50)
        def external(node):
            if node.actor==-1:return {}
            actions=[a if not a.startswith('BET ') else 'BET 50.000000' for a in node.actions]
            reversed_actions=list(reversed(actions))
            return {'player':1-node.actor,'actions':reversed_actions,'strategy':{'strategy':{hand:[.5,.49999998] for hand,_ in game.ranges[node.actor]}},'childrens':{a:external(child) for a,child in zip(actions,node.children)}}
        policy=convert_policy(game,external(game.root))
        self.assertEqual(set(policy),game.keys)
        self.assertTrue(all(abs(sum(row)-1)<1e-12 for row in policy.values()))
        self.assertAlmostEqual(sum(game.measure(policy)['policy_payoffs']),0)

    def test_plus_has_normalized_policies_for_every_player_count(self):
        for n in range(2,7):
            game=RiverGame(BOARD,[r[:1] for r in demo_ranges(n)])
            policy=game.train(8,method='cfr_plus')
            self.assertEqual(set(policy),game.keys)
            for row in policy.values():
                self.assertAlmostEqual(sum(row),1)
                self.assertTrue(all(0<=v<=1 for v in row))
            self.assertAlmostEqual(sum(game.measure(policy)['policy_payoffs']),0)

    def test_plus_meets_headsup_control_threshold_at_same_iteration_budget(self):
        game=RiverGame(BOARD,demo_ranges(2))
        classic=game.measure(game.train(200))
        improved=game.measure(game.train(200,method='cfr_plus'))
        self.assertLess(improved['max_unilateral_gain_pct_pot'],.1)
        self.assertLess(improved['nash_conv_chips'],classic['nash_conv_chips']/10)

    def test_plus_is_repeatable_and_handles_joint_card_collisions(self):
        game=RiverGame(BOARD,[[('AhAd',1),('QhQd',.2)],[('AhAd',.5),('KhKd',1)]])
        first=game.train(30,method='cfr_plus')
        second=game.train(30,method='cfr_plus')
        self.assertEqual(first,second)
        self.assertAlmostEqual(sum(game.measure(first)['policy_payoffs']),0)
        for bad in (0,True,2001,1.5):
            with self.assertRaises(ValueError):game.train(bad,method='cfr_plus')
        with self.assertRaises(ValueError):game.train(20,method='unknown')
