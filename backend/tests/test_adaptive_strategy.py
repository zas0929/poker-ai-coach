import copy
from types import SimpleNamespace
import unittest
from research.benchmark_expanded import make_case
from research.custom_river import RiverGame,Node
from research.adaptive_strategy import action_values,train_adaptive

BOARD=['2c','4d','7h','9s','Jc']


def fixture():
    spec=make_case('test',BOARD,[8,8],17)['input'];spec.update(raise_sizes=[],max_raises=0)
    return RiverGame(**spec)


class AdaptiveStrategyTests(unittest.TestCase):
    def test_hidden_deals_are_aggregated_before_best_action(self):
        left=Node(-1,((0,'LEFT'),));right=Node(-1,((0,'RIGHT'),))
        root=Node(0,(),actions=('LEFT','RIGHT'),children=(left,right))
        fake=SimpleNamespace(n=2,live=(0,1),root=root,
            deals=[(('AhAd','KhKd'),.5,None),(('AhAd','QhQd'),.5,None)],
            utilities={(id(left),0):(10.,-10.),(id(left),1):(-10.,10.),
                       (id(right),0):(-10.,10.),(id(right),1):(10.,-10.)},
            measure=lambda policy:None,key=lambda node,d:(0,'AhAd',()))
        values=action_values(fake,{(0,'AhAd',()):[.5,.5]})
        self.assertEqual(values[(0,'AhAd',())]['q'],[0.,0.])
        self.assertEqual(values[(0,'AhAd',())]['mass'],1.)

    def test_zero_split_budget_rejects_without_claiming_quality(self):
        source=fixture();deals=copy.deepcopy(source.deals)
        policy,evidence=train_adaptive(source,iterations=100,max_splits=0,max_strategy_rows=len(source.keys),method='cfr_plus_indexed')
        self.assertEqual(evidence['status'],'rejected')
        self.assertEqual(evidence['reason'],'split_budget_exhausted')
        self.assertEqual(len(evidence['history']),1);self.assertEqual(evidence['splits'],[])
        self.assertEqual(source.deals,deals);self.assertEqual(set(policy),source.keys)
        self.assertFalse(evidence['live_advice_allowed'])

    def test_initial_row_budget_refuses_before_training(self):
        source=fixture();policy,evidence=train_adaptive(source,max_strategy_rows=1,method='cfr_plus_indexed')
        self.assertIsNone(policy);self.assertEqual(evidence['reason'],'initial_row_budget')
        self.assertIsNone(evidence['metrics_original_game'])
        self.assertEqual(evidence['history'],[])

    def test_refinement_preserves_original_policy_and_obeys_all_row_limits(self):
        source=fixture();budget=len(source.keys)*3//4
        policy,evidence=train_adaptive(source,iterations=100,max_splits=6,max_strategy_rows=budget,method='cfr_plus_indexed')
        self.assertGreater(len(evidence['splits']),0)
        self.assertLessEqual(len(evidence['splits']),6)
        rows=[h['grouped_strategy_rows'] for h in evidence['history']]
        self.assertEqual(rows,sorted(set(rows)))
        self.assertTrue(all(r<=budget for r in rows))
        self.assertEqual(source.measure(policy),evidence['metrics_original_game'])
        self.assertLess(evidence['history'][-1]['max_unilateral_gain_pct_pot'],evidence['history'][0]['max_unilateral_gain_pct_pot'])
        for split in evidence['splits']:self.assertGreater(split['priority_chips'],0.)
        self.assertEqual(evidence['status'],'ready')
        self.assertLessEqual(evidence['metrics_original_game']['max_unilateral_gain_pct_pot'],.5)
        self.assertLess(rows[-1],len(source.keys))

    def test_group_limit_refuses_instead_of_silently_increasing_budget(self):
        source=fixture()
        _,evidence=train_adaptive(source,iterations=100,max_splits=3,max_groups_per_seat=2,max_strategy_rows=len(source.keys),method='cfr_plus_indexed')
        self.assertEqual(evidence['status'],'rejected');self.assertEqual(evidence['reason'],'no_split_within_budget')
        self.assertEqual(len(evidence['history']),1)

    def test_invalid_limits_fail_closed(self):
        source=fixture()
        for change in ({'iterations':True},{'iterations':0},{'max_splits':33},{'max_groups_per_seat':1},
                       {'max_strategy_rows':True},{'max_strategy_rows':len(source.keys)+1},
                       {'quality_gate_pct_pot':.6},{'quality_gate_pct_pot':float('nan')},{'method':'auto'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                train_adaptive(source,**{'max_strategy_rows':len(source.keys),'method':'cfr_plus_indexed',**change})
