import json
import math
import subprocess
import unittest
from unittest.mock import patch
from research.benchmark_capacity import scenarios,run_case,worker,suite_passes
from research.custom_river import RiverGame


class SolverCapacityTests(unittest.TestCase):
    def test_fixed_suite_has_uncertainty_at_every_live_seat_and_no_truncation(self):
        cases=list(scenarios())
        self.assertEqual(cases,list(scenarios()))
        self.assertEqual(len(cases),11)
        for case in cases[:-1]:
            spec=case['input']
            self.assertTrue(all(len(r)>=2 for r in spec['ranges']))
            self.assertLessEqual(math.prod(len(r) for r in spec['ranges']),64)
            game=RiverGame(**spec)
            self.assertGreater(len(game.deals),0)
        self.assertEqual(worker(cases[-1],1)['status'],'rejected')

    def test_isolated_worker_completes_and_measures_memory_and_quality(self):
        case=next(scenarios())
        result=run_case(case,2,15)
        self.assertEqual(result['status'],'completed',result)
        self.assertGreater(result['peak_rss_mib'],0)
        self.assertGreater(result['joint_deals'],0)
        self.assertAlmostEqual(sum(result['metrics']['policy_payoffs']),0)
        self.assertEqual(result['passes_quality_gate'],result['metrics']['max_unilateral_gain_pct_pot']<=.5)

    def test_timeout_never_claims_a_policy_quality_or_final_memory_peak(self):
        output=json.dumps({'phase':'train','observed_peak_rss_mib':30})+'\n'+ '{"status":'
        with patch('research.benchmark_capacity.subprocess.run',side_effect=subprocess.TimeoutExpired('worker',.1,output=output)):
            result=run_case(next(scenarios()),2,.1)
        self.assertEqual(result['status'],'timed_out')
        self.assertEqual(result['last_phase'],'train')
        self.assertEqual(result['last_observed_peak_rss_mib'],30)
        self.assertNotIn('metrics',result)
        self.assertNotIn('passes_quality_gate',result)
        self.assertNotIn('peak_rss_mib',result)

    def test_worker_failure_is_not_mislabeled_as_quality_failure(self):
        failure=subprocess.CompletedProcess([],1,'','diagnostic error')
        with patch('research.benchmark_capacity.subprocess.run',return_value=failure):
            result=run_case(next(scenarios()),2,1)
        self.assertEqual(result['status'],'error')
        self.assertNotIn('metrics',result)

    def test_suite_gate_requires_complete_quality_results_and_the_expected_limit_error(self):
        good=[{'status':'completed','passes_quality_gate':True},
              {'expected_rejection':True,'status':'rejected','reason':'At most 64 raw joint combinations'}]
        self.assertTrue(suite_passes(good))
        for bad in ({'status':'timed_out'},{'status':'error'},
                    {'status':'completed','passes_quality_gate':False},
                    {'expected_rejection':True,'status':'rejected','reason':'Invalid card'}):
            self.assertFalse(suite_passes([*good,bad]))
