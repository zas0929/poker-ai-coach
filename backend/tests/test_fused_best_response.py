import copy
import unittest
from types import SimpleNamespace
from research.custom_river import RiverGame,Node
from research.benchmark_expanded import make_case
from research.adaptive_strategy import action_values,train_adaptive
from research.adaptive_strategy_fast import train_adaptive_fast
from research.fused_best_response import evaluate_policy
from research.benchmark_sidepots import scenarios as sidepots

BOARD=['2c','4d','7h','9s','Jc']


def uniform(game):return {k:[1./count]*count for k,count in game.action_counts.items()}


class FusedBestResponseTests(unittest.TestCase):
    def check(self,game,policy):
        metrics,records=evaluate_policy(game,policy)
        self.assertEqual(metrics,game.measure(policy))
        self.assertEqual(records,action_values(game,policy))

    def test_uniform_and_trained_policies_two_to_six_seats(self):
        for n in range(2,7):
            spec=make_case('test',BOARD,[2]*n,101+n)['input'];spec.update(raise_sizes=[],max_raises=0)
            game=RiverGame(**spec)
            with self.subTest(n=n):
                self.check(game,uniform(game));self.check(game,game.train(10,method='cfr_plus_indexed'))

    def test_short_stacks_sidepots_and_odd_chip_ties(self):
        for name,spec in sidepots():
            if len(spec['ranges'])>3:continue
            with self.subTest(name=name,players=len(spec['ranges'])):
                self.check(RiverGame(**spec),uniform(RiverGame(**spec)))

    def test_folded_seat_values_and_zero_opponent_reach(self):
        ranges=[[('AhAd',1.),('QhQd',3.)],[('KhKd',1.),('6h6d',2.)],[]]
        game=RiverGame(BOARD,ranges,pot=90,initial_contributions=[30]*3,stacks=[50]*3,folded=[2],bet_sizes=[10],raise_sizes=[20],max_raises=1)
        policy={k:[1.]+[0.]*(count-1) for k,count in game.action_counts.items()}
        self.check(game,policy)
        _,records=evaluate_policy(game,policy)
        self.assertTrue(any(r['mass']==0. for r in records.values()))
        self.assertTrue(all(key[0]!=2 for key in records))

    def test_complete_adaptive_paths_and_refusals_are_identical(self):
        spec=make_case('test',BOARD,[8,8],17)['input'];spec.update(raise_sizes=[],max_raises=0)
        game=RiverGame(**spec);original=copy.deepcopy(game.deals)
        for changes in ({'max_splits':0},{'max_splits':6},{'max_strategy_rows':1},{'max_groups_per_seat':2}):
            args={'iterations':50,'max_strategy_rows':len(game.keys)*3//4,'method':'cfr_plus_indexed',**changes}
            self.assertEqual(train_adaptive(game,**args),train_adaptive_fast(game,**args))
        self.assertEqual(game.deals,original)

    def test_hidden_information_is_not_used_to_pick_per_deal_action(self):
        left=Node(-1,((0,'LEFT'),));right=Node(-1,((0,'RIGHT'),))
        root=Node(0,(),actions=('LEFT','RIGHT'),children=(left,right))
        key=(0,'AhAd',())
        fake=SimpleNamespace(n=2,root=root,keys={key},action_counts={key:2},decision_pot=100,
            deals=[(('AhAd','KhKd'),.5,None),(('AhAd','QhQd'),.5,None)],
            utilities={(id(left),0):(10.,-10.),(id(left),1):(-10.,10.),
                       (id(right),0):(-10.,10.),(id(right),1):(10.,-10.)},
            key=lambda node,d:key)
        metrics,records=evaluate_policy(fake,{key:[.5,.5]})
        self.assertEqual(records[key]['q'],[0.,0.])
        self.assertEqual(metrics['best_response_payoffs'],[0.,0.])
        self.assertEqual(metrics['max_unilateral_gain_pct_pot'],0.)

    def test_refinement_evaluation_reads_terminal_payoffs_once_instead_of_five_times(self):
        from research.benchmark_fused_response import CountUtilities,reference
        game=RiverGame(BOARD,[[('AhAd',1.),('QhQd',3.)],[('KhKd',1.)]],bet_sizes=[10])
        policy=uniform(game);base=game.utilities;reads=[]
        try:
            for fn in (reference,evaluate_policy):
                counted=CountUtilities(base);game.utilities=counted;fn(game,policy);reads.append(counted.reads)
        finally:game.utilities=base
        self.assertEqual(reads[0],5*reads[1])

    def test_invalid_policies_and_budgets_fail_closed(self):
        game=RiverGame(BOARD,[[('AhAd',1.)],[('KhKd',1.)]],bet_sizes=[10])
        for policy in ({},{k:[float('nan')]*count for k,count in game.action_counts.items()}):
            with self.assertRaises(ValueError):evaluate_policy(game,policy)
        for changes in ({'iterations':True},{'max_splits':33},{'max_strategy_rows':True},{'quality_gate_pct_pot':1.},{'method':'auto'}):
            with self.assertRaises(ValueError):train_adaptive_fast(game,**{'max_strategy_rows':len(game.keys),**changes})
