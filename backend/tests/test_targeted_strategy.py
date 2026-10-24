from types import SimpleNamespace
import unittest
from research.targeted_strategy import propose_targeted_split
from research.adaptive_strategy_targeted import train_adaptive_targeted
from research.benchmark_expanded import make_case
from research.custom_river import RiverGame
from research.benchmark_targeted_strategy import summarize


class TargetedStrategyTests(unittest.TestCase):
    def fixture(self):
        keys={(p,h,()) for p in (0,1) for h in ('A','B')}
        game=SimpleNamespace(n=2,keys=keys,action_counts={k:2 for k in keys},nodes=[],root=None,deals=[],utilities={})
        mapping=[{'A':'g','B':'g'} for _ in (0,1)]
        records={(p,h,()):{'q':([10.,0.] if h=='A' else [0.,10.])} for p in (0,1) for h in ('A','B')}
        return game,mapping,records

    def test_targets_highest_gain_and_breaks_ties_by_seat(self):
        game,mapping,records=self.fixture()
        for gains,expected in (([1.,5.],1),([5.,5.],0)):
            p=propose_targeted_split(game,mapping,records,8,8,{'unilateral_gains':gains})
            self.assertEqual(p['seat'],expected);self.assertEqual(p['target_unilateral_gain_chips'],gains[expected])

    def test_falls_back_when_largest_gain_seat_cannot_split(self):
        game,mapping,records=self.fixture();mapping[1]={'A':'a','B':'b'}
        p=propose_targeted_split(game,mapping,records,2,8,{'unilateral_gains':[1.,5.]})
        self.assertEqual(p['seat'],0)
        self.assertIsNone(propose_targeted_split(game,mapping,records,2,1,{'unilateral_gains':[1.,5.]}))

    def test_invalid_metrics_refuse(self):
        game,mapping,records=self.fixture()
        for gains in ([1.],[-1.,2.],[float('nan'),1.]):
            with self.assertRaises(ValueError):propose_targeted_split(game,mapping,records,8,8,{'unilateral_gains':gains})

    def test_complete_policy_strict_quality_and_refusal(self):
        spec=make_case('test',['2c','4d','7h','9s','Jc'],[6,6],101)['input'];spec.update(raise_sizes=[],max_raises=0)
        game=RiverGame(**spec)
        for max_splits in (0,6):
            policy,e=train_adaptive_targeted(game,iterations=30,max_splits=max_splits,max_strategy_rows=len(game.keys)*3//4,method='cfr_plus_indexed')
            self.assertEqual(game.measure(policy),e['metrics_original_game']);self.assertFalse(e['live_advice_allowed'])
            self.assertEqual(e['status']=='ready',e['metrics_original_game']['max_unilateral_gain_pct_pot']<=.5)
            self.assertTrue(all(h['grouped_strategy_rows']<=len(game.keys)*3//4 for h in e['history']))

    def test_summary_counts_regressions_and_excludes_unpaired_timeout(self):
        c={'live_players':4}
        def row(a,b):return {'case':c,'methods':{m:{'status':'completed','evidence':{'status':s}} for m,s in [('reference',a),('targeted',b)]}}
        rows=[row('ready','rejected'),row('rejected','ready'),{'case':c,'methods':{'reference':{'status':'timed_out'},'targeted':{'status':'completed','evidence':{'status':'ready'}}}}]
        s=summarize(rows)['overall'];self.assertEqual(s['improved'],1);self.assertEqual(s['regressed'],1);self.assertEqual(s['both_completed'],2)
