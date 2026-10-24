from collections import Counter
import unittest
from research.deal_sampling import sample_joint_ranges,SampleView
from research.custom_river import RiverGame
from research.fused_best_response import evaluate_policy
from research.indexed_cfr import train_indexed

BOARD=['2c','4d','7h','9s','Jc']


class DealSamplingTests(unittest.TestCase):
    def draw(self,ranges,**kwargs):return sample_joint_ranges(BOARD,ranges,samples=4096,seed=11,max_attempts=100000,**kwargs)

    def test_weighted_law_rejects_entire_collision_instead_of_repairing_seat(self):
        ranges=[[('AhAd',1.),('AcAs',3.)],[('AhKd',2.),('KhKs',1.)]]
        draw=self.draw(ranges);self.assertEqual(draw['status'],'sampled')
        # Legal products: 1, 6, 3; conditioning gives .1/.6/.3.
        expected={('AhAd','KhKs'):.1,('AcAs','AhKd'):.6,('AcAs','KhKs'):.3}
        self.assertEqual(set(draw['counts']),set(expected))
        for texts,p in expected.items():self.assertAlmostEqual(draw['counts'][texts]/4096,p,delta=.035)
        self.assertGreater(draw['attempts'],4096);self.assertEqual(draw,self.draw(ranges))

    def test_impossible_support_exhausts_budget_without_partial_training(self):
        draw=sample_joint_ranges(BOARD,[[('AhAd',1.)],[('AhKd',1.)]],samples=4,seed=1,max_attempts=7)
        self.assertEqual(draw['status'],'proposal_budget_exhausted');self.assertEqual(draw['attempts'],7)
        game=RiverGame(BOARD,[[('AhAd',1.)],[('KhKd',1.)]],bet_sizes=[10])
        with self.assertRaises(ValueError):SampleView(game,draw)

    def test_folded_slots_and_real_card_compatibility(self):
        ranges=[[('AhAd',1.)],[('KhKd',1.)],[]]
        draw=self.draw(ranges,folded=[2]);self.assertEqual(draw['counts'],{('AhAd','KhKd',None):4096})
        for bad in ({'samples':True,'seed':1,'max_attempts':10},{'samples':10,'seed':-1,'max_attempts':100}):
            with self.assertRaises(ValueError):sample_joint_ranges(BOARD,ranges,folded=[2],**bad)

    def test_empirical_view_preserves_payoffs_and_explicit_missing_coverage(self):
        ranges=[[('AhAd',1.),('QhQd',3.)],[('KhKd',1.)]]
        game=RiverGame(BOARD,ranges,bet_sizes=[10],utility_storage='compact')
        draw=sample_joint_ranges(BOARD,ranges,samples=1,seed=11,max_attempts=10);view=SampleView(game,draw)
        self.assertTrue(view.missing_keys);self.assertLess(view.keys,game.keys)
        source={t:d for d,(t,_,_) in enumerate(game.deals)}
        for node in game.nodes:
            if node.actor==-1:
                for d,(texts,_,_) in enumerate(view.deals):self.assertEqual(view.utilities[(id(node),d)],game.utilities[(id(node),source[texts])])
        policy=train_indexed(view,10);evaluate_policy(view,policy)
        with self.assertRaises(ValueError):evaluate_policy(game,policy)

    def test_complete_coverage_policy_evaluates_in_original_game(self):
        ranges=[[('AhAd',1.),('QhQd',3.)],[('KhKd',1.)]]
        game=RiverGame(BOARD,ranges,bet_sizes=[10]);view=SampleView(game,self.draw(ranges))
        self.assertEqual(view.keys,game.keys);self.assertAlmostEqual(sum(w for _,w,_ in view.deals),1.)
        policy=train_indexed(view,10);evaluate_policy(game,policy)
