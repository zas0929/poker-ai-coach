import copy
import unittest
from research.reallocation_cycle import run_cycle,better,encode,decode


def cp(gain=1.,rows=6,label='a'):
    return {'metrics':{'max_unilateral_gain_pct_pot':gain},'rows':rows,'mapping':[{'A':label,'B':'b'},{}],'policy':[]}


class ReallocationCycleTests(unittest.TestCase):
    def runner(self,trials,base=None):
        calls=[];base=cp() if base is None else base
        def run(job,*args,**kwargs):
            calls.append(job)
            if job['kind']=='baseline':return {'status':'completed','checkpoint':copy.deepcopy(base),'baseline_evidence':{'limits':{'max_strategy_rows':8}}}
            return copy.deepcopy(trials.pop(0))
        return run,calls

    def test_timed_out_trial_preserves_completed_baseline(self):
        run,calls=self.runner([{'status':'timed_out'}]);r=run_cycle({},_runner=run)
        self.assertEqual(r['best_checkpoint'],cp());self.assertEqual(r['status'],'rejected');self.assertEqual(r['reason'],'trial_timed_out')

    def test_completed_improvement_survives_later_failure(self):
        improved=cp(.8,5);improved['mapping'][0]={'A':'x','B':'x'}
        run,calls=self.runner([{'status':'completed','checkpoint':improved},{'status':'memory_exceeded'}])
        r=run_cycle({},_runner=run);self.assertEqual(r['best_checkpoint'],improved)
        self.assertEqual(r['reason'],'trial_memory_exceeded');self.assertFalse(r['live_advice_allowed'])

    def test_existing_pass_skips_trials_and_new_pass_stops(self):
        run,calls=self.runner([],cp(.1));self.assertEqual(run_cycle({},_runner=run)['status'],'ready');self.assertEqual(len(calls),1)
        good=cp(.1);good['mapping'][0]={'A':'x','B':'x'}
        run,calls=self.runner([{'status':'completed','checkpoint':good}])
        self.assertEqual(run_cycle({},_runner=run)['status'],'ready');self.assertEqual(len(calls),2)

    def test_worse_and_relabelled_partition_cannot_replace_best(self):
        run,calls=self.runner([{'status':'completed','checkpoint':cp(.8,label='new')},{'status':'completed','checkpoint':cp(2.)}])
        r=run_cycle({},_runner=run);self.assertEqual(r['best_checkpoint'],cp());self.assertEqual(len(calls),3)

    def test_expired_budget_does_not_start_trial(self):
        run,calls=self.runner([]);times=iter([0.,45.,45.])
        r=run_cycle({},_runner=run,_clock=lambda:next(times));self.assertEqual(r['reason'],'time_budget');self.assertEqual(len(calls),1)

    def test_policy_roundtrip_and_duplicate_rejection(self):
        p={(0,'AhAd',((1,'CALL'),)):[.25,.75]};self.assertEqual(decode(encode(p)),p)
        with self.assertRaises(ValueError):decode(encode(p)*2)
        for kw in ({'max_cycles':3},{'total_seconds':46},{'max_candidates':3}):
            with self.assertRaises(ValueError):run_cycle({},**kw)
        self.assertFalse(better(cp(2.,1),cp(1.,6)))
