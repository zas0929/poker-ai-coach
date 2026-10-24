import contextlib
import copy
import io
import math
import unittest
from unittest.mock import patch
from research.benchmark_midriver_ranges import scenarios,benchmark
from research.benchmark_capacity import worker
from research.river_snapshot import build_river_from_snapshot
from research.sidepot_reference import compare_every_path


class MidriverRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.cases=list(scenarios())

    def test_fixed_public_cases_have_uncertainty_at_every_live_seat(self):
        self.assertEqual(self.cases,list(scenarios()))
        self.assertEqual(len(self.cases),16)
        for case in self.cases:
            snapshot=case['snapshot'];chosen=case['selected_hands']
            live={p['id'] for p in snapshot['players'] if p['status']!='folded'}
            self.assertEqual(set(chosen),live)
            self.assertTrue(all(len(r)>=2 for r in chosen.values()))
            self.assertEqual(case['raw_combinations'],math.prod(map(len,chosen.values())))
            self.assertGreater(case['raw_combinations'],64)
            self.assertTrue(any(a['street']=='river' for a in snapshot['history']))
            for player in snapshot['players']:
                if player['id'] not in live:continue
                public={row['cards']:row['weight'] for row in player['range']}
                self.assertEqual(case['selected_public_weights'][player['id']],
                                 [{'cards':text,'weight':public[text]} for text in chosen[player['id']]])
            self.assertTrue(all('cards' not in p for p in snapshot['players']))

    def test_public_worker_matches_direct_solve_and_engine_with_collisions(self):
        case=next(c for c in self.cases if c['name']=='dry_3')
        game,meta=build_river_from_snapshot(case['snapshot'],case['selected_hands'],**case['input'])
        self.assertLess(len(game.deals),case['raw_combinations'])
        self.assertTrue(all(len(r)>1 for r in game.ranges))
        compare_every_path(game)
        expected=game.measure(game.train(3,method='cfr_plus_indexed'))
        with contextlib.redirect_stdout(io.StringIO()):result=worker(case,3,method='cfr_plus_indexed')
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['public_input_metadata'],meta)
        self.assertEqual(result['metrics'],expected)
        self.assertEqual(result['passes_quality_gate'],expected['max_unilateral_gain_pct_pot']<=.5)
        self.assertEqual(result['joint_deals'],len(game.deals))
        self.assertEqual(result['compatible_range_counts'],[len({d[0][p] for d in game.deals}) for p in range(game.n)])
        self.assertTrue(all(n>=2 for n in result['compatible_range_counts']))

    def test_short_raise_reopening_and_folded_uncertainty_are_retained(self):
        for name,reopened in [('short_closed_3',False),('short_reopened_4',True)]:
            case=next(c for c in self.cases if c['name']==name)
            game,meta=build_river_from_snapshot(case['snapshot'],case['selected_hands'],**case['input'])
            self.assertEqual(any(a.startswith('RAISE') for a in game.root.actions),reopened)
            self.assertGreater(meta['river_state']['observed_raises'],0)
            compare_every_path(game)
        case=next(c for c in self.cases if c['name']=='river_fold_4')
        game,_=build_river_from_snapshot(case['snapshot'],case['selected_hands'],**case['input'])
        self.assertEqual(len(game.folded),1)
        self.assertEqual(game.ranges[game.folded[0]],[])
        self.assertTrue(all(deal[0][game.folded[0]] is None for deal in game.deals))

    def test_bad_public_input_is_rejected_in_worker(self):
        case=copy.deepcopy(self.cases[0]);case['snapshot']['pot']+=1
        with contextlib.redirect_stdout(io.StringIO()):result=worker(case,2,method='cfr_plus_indexed')
        self.assertEqual(result['status'],'rejected')
        self.assertNotIn('metrics',result)
        self.assertNotIn('passes_quality_gate',result)

    def test_followup_selection_rejects_unknown_or_duplicate_cases(self):
        for names in ([],['missing'],['dry_6','dry_6']):
            with patch('research.benchmark_midriver_ranges.run_guarded') as runner:
                with self.assertRaises(ValueError):benchmark(names=names)
                runner.assert_not_called()

    def test_budget_failure_is_reported_without_quality_credit(self):
        with patch('research.benchmark_midriver_ranges.run_guarded',return_value={'status':'timed_out'}):
            with contextlib.redirect_stderr(io.StringIO()):report=benchmark(names=['dry_2'])
        self.assertEqual(report['summary']['completed'],0)
        self.assertEqual(report['summary']['quality_passed'],0)
        self.assertNotIn('snapshot',report['results'][0])
        self.assertNotIn('metrics',report['results'][0])
