import copy
import math
import unittest
from unittest.mock import patch
from research.custom_river import RiverGame
from research.benchmark_expanded import scenarios,run_guarded,benchmark
from research.river_snapshot import build_river_from_snapshot
from research.benchmark_snapshot import control,select


class ExpandedRangeTests(unittest.TestCase):
    def test_default_limit_is_preserved_and_explicit_budget_never_truncates(self):
        spec=copy.deepcopy(next(scenarios())['input']);spec.pop('max_joint_combos')
        with self.assertRaisesRegex(ValueError,'64 raw joint'):RiverGame(**spec)
        game=RiverGame(**spec,max_joint_combos=144)
        self.assertEqual([len(r) for r in game.ranges],[12,12])
        self.assertEqual(game.max_joint_combos,144)
        self.assertGreater(len(game.deals),64)
        for bad in (0,True,4097,1.5):
            with self.assertRaises(ValueError):RiverGame(**spec,max_joint_combos=bad)

    def test_larger_raw_budget_cannot_bypass_the_node_deal_limit(self):
        board=['2c','4d','7h','9s','Jc']
        deck=[r+s for r in '23456789TJQKA' for s in 'cdhs' if r+s not in board]
        ranges=[[(deck[(8*p+2*h)%47]+deck[(8*p+2*h+1)%47],1) for h in range(4)] for p in range(6)]
        with self.assertRaisesRegex(ValueError,'one million'):
            RiverGame(board,ranges,pot=360,stacks=[100]*6,initial_contributions=[60]*6,
                      bet_sizes=(40,),raise_sizes=(80,),max_raises=1,max_joint_combos=4096)

    def test_expanded_indexed_and_reference_policies_match(self):
        game=RiverGame(**next(scenarios())['input'])
        reference=game.train(10,method='cfr_plus')
        indexed=game.train(10,method='cfr_plus_indexed')
        for key,row in reference.items():
            for a,b in zip(row,indexed[key]):self.assertAlmostEqual(a,b,places=12)
        self.assertEqual(game.measure(reference),game.measure(indexed))

    def test_fixed_expanded_suite_has_no_single_hand_seats(self):
        cases=list(scenarios())
        self.assertEqual(cases,list(scenarios()))
        self.assertEqual(len(cases),13)
        self.assertTrue(all(c['raw_combinations']==math.prod(len(r) for r in c['input']['ranges']) for c in cases))
        self.assertTrue(all(c['raw_combinations']>64 for c in cases))
        self.assertTrue(all(len(r)>=2 for c in cases for r in c['input']['ranges']))

    def test_public_adapter_preserves_explicit_resource_budget_in_identity(self):
        snapshot=control(2);chosen=select(snapshot)
        _,a=build_river_from_snapshot(snapshot,chosen,bet_sizes=(10,))
        game,b=build_river_from_snapshot(snapshot,chosen,bet_sizes=(10,),max_joint_combos=144)
        self.assertEqual(game.max_joint_combos,144)
        self.assertNotEqual(a['task_key'],b['task_key'])
        self.assertEqual(a['source_information_key'],b['source_information_key'])


class ExternalBudgetTests(unittest.TestCase):
    def case(self):return next(scenarios())

    def test_timeout_does_not_export_metrics(self):
        result=run_guarded(self.case(),iterations=100,timeout_seconds=.001,poll_seconds=.01)
        self.assertEqual(result['status'],'timed_out',result)
        self.assertNotIn('metrics',result)

    def test_rss_budget_does_not_export_accepted_quality(self):
        result=run_guarded(self.case(),iterations=2,memory_mib=1,poll_seconds=.01)
        self.assertEqual(result['status'],'memory_exceeded',result)
        self.assertNotIn('passes_quality_gate',result)
        self.assertNotIn('metrics',result)

    def test_missing_monitor_is_explicit_failure(self):
        with patch('research.benchmark_expanded.read_rss_mib',side_effect=OSError('ps unavailable')):
            result=run_guarded(self.case(),iterations=100)
        self.assertEqual(result['status'],'monitor_error',result)
        self.assertNotIn('metrics',result)

    def test_invalid_budgets_are_rejected_before_launch(self):
        for kwargs in ({'iterations':True},{'timeout_seconds':float('inf')},{'memory_mib':0},{'memory_mib':True},{'memory_mib':None},{'poll_seconds':-1}):
            with self.assertRaises(ValueError):run_guarded(self.case(),**kwargs)

    def test_followup_selection_cannot_silently_run_an_empty_or_wrong_suite(self):
        for names in ([],['missing'],['dry_6','dry_6']):
            with patch('research.benchmark_expanded.run_guarded') as runner:
                with self.assertRaises(ValueError):benchmark(names=names)
                runner.assert_not_called()
