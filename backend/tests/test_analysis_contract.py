import contextlib
import copy
import io
import json
import math
import unittest
from unittest.mock import patch
from research.analysis_contract import (ResearchLimits,analyze,provenance,worker,valid_quality,recheck_decision,expected_root_actions)
from research.benchmark_midriver_ranges import make_case
from research.river_snapshot import digest


class AnalysisContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        case=make_case('contract',2,[3,3],20261047)
        cls.request={k:case[k] for k in ('snapshot','selected_hands','input')}
        cls.request['own_hand']=case['selected_hands'][case['snapshot']['actor_id']][0]

    def completed(self):
        # Coherent deterministic worker evidence; gate decisions are tested independently of CFR.
        request=self.request
        return {'status':'completed','iterations':100,'provenance':provenance(),'request_key':digest(request),
            'wall_seconds':.1,'peak_rss_mib':30.,'sampled_peak_rss_mib':29.,
            'tree':{'bet_sizes':[10,40],'raise_sizes':[80,120],'future_raise_cap':1,'min_bet':10,
                    'max_nodes':20000,'max_joint_combos':4096,'public_nodes':9,'joint_deals':4},
            'metadata':{'source_information_key':request['snapshot']['information_key'],'task_key':'a'*64},
            'metrics':{'policy_payoffs':[0.,0.],'best_response_payoffs':[0.,0.],
                       'unilateral_gains':[0.,0.],'nash_conv_chips':0.,'max_unilateral_gain_pct_pot':0.},
            'candidate':{'actor_id':request['snapshot']['actor_id'],'own_hand':request['own_hand'],
                         'actions':expected_root_actions(request),'probabilities':[1/len(expected_root_actions(request))]*len(expected_root_actions(request)),
                         'compatible_deals':2,'conditional_mass':.5}}

    def run_raw(self,raw,limits=None):
        with patch('research.analysis_contract.run_guarded',return_value=raw):return analyze(self.request,limits)

    def assert_closed(self,result,status):
        self.assertEqual(result['status'],status,result)
        self.assertIsNone(result['candidate'])
        self.assertFalse(result['admission']['offline_analysis_allowed'])
        self.assertFalse(result['admission']['live_advice_allowed'])
        self.assertTrue(result['fallback']['retain_current_advice'])
        self.assertTrue(result['reasons'])
        json.dumps(result,allow_nan=False)

    def test_ready_is_explicitly_offline_and_retains_coach(self):
        result=self.run_raw(self.completed())
        self.assertEqual(result['status'],'ready')
        self.assertTrue(result['admission']['offline_analysis_allowed'])
        self.assertFalse(result['admission']['live_advice_allowed'])
        self.assertTrue(result['fallback']['retain_current_advice'])
        self.assertIsNotNone(result['candidate'])
        self.assertEqual(result['quality']['value'],0.)
        self.assertEqual(result['limits']['iterations'],100)

    def test_limits_reject_coercion_nonfinite_and_loosened_gate(self):
        for kwargs in ({'iterations':True},{'iterations':0},{'iterations':2001},
                       {'wall_seconds':True},{'wall_seconds':float('nan')},{'wall_seconds':10**400},
                       {'memory_mib':0},{'quality_gate_pct_pot':.51}):
            with self.assertRaises(ValueError):ResearchLimits(**kwargs)
        for bad in ({},False,0):
            with self.assertRaises(ValueError):analyze(self.request,bad)

    def test_private_input_and_stale_decisions_never_dispatch(self):
        bad=copy.deepcopy(self.request);bad['snapshot']['players'][0]['cards']=['Ah','Ad']
        with patch('research.analysis_contract.run_guarded') as runner:
            self.assert_closed(analyze(bad),'invalid_input')
            self.assert_closed(analyze(self.request,expected_source_key='obsolete'),'stale')
            bad=copy.deepcopy(self.request);bad['snapshot']['street']='turn'
            self.assert_closed(analyze(bad),'unsupported')
            runner.assert_not_called()

    def test_failed_workers_never_expose_even_an_attached_candidate(self):
        statuses={'timed_out':'budget_exceeded','memory_exceeded':'budget_exceeded',
                  'monitor_error':'error','rejected':'unsupported','invalid_probe':'unsupported',
                  'provider_unavailable':'unavailable','error':'error','unknown':'error'}
        for source,target in statuses.items():
            raw=self.completed();raw['status']=source
            self.assert_closed(self.run_raw(raw),target)

    def test_final_budget_check_catches_exit_between_monitor_polls(self):
        for field,value in [('wall_seconds',10.01),('peak_rss_mib',129.),('sampled_peak_rss_mib',129.)]:
            raw=self.completed();raw[field]=value
            self.assert_closed(self.run_raw(raw),'budget_exceeded')
        raw=self.completed();raw['peak_rss_mib']=float('nan')
        self.assert_closed(self.run_raw(raw),'error')
        raw=self.completed();raw.pop('peak_rss_mib')
        self.assert_closed(self.run_raw(raw),'error')

    def test_quality_is_measured_not_inferred_from_iteration_count(self):
        raw=self.completed();pot=self.request['snapshot']['pot']
        raw['metrics'].update(best_response_payoffs=[pot*.006,0],unilateral_gains=[pot*.006,0],
                              nash_conv_chips=pot*.006,max_unilateral_gain_pct_pot=.6)
        self.assert_closed(self.run_raw(raw),'quality_rejected')
        raw=self.completed();raw['metrics']['max_unilateral_gain_pct_pot']=float('nan')
        self.assert_closed(self.run_raw(raw),'error')
        raw=self.completed();raw['metrics']['best_response_payoffs']=[1.,0.]
        self.assert_closed(self.run_raw(raw),'error')
        self.assertFalse(valid_quality({},2,100))

    def test_wrong_identity_and_malformed_strategies_are_rejected(self):
        for key,value in [('request_key','wrong'),('iterations',99),('provenance',{}),('metadata',None),('tree',None)]:
            raw=self.completed();raw[key]=value
            self.assert_closed(self.run_raw(raw),'error')
        for key,value in [('probabilities',[.4,.4]),('probabilities',[float('nan'),1.]),
                          ('actions',[{},'CALL']),('actions',['UNKNOWN','CALL']),
                          ('own_hand','QhQd'),('actor_id','wrong'),('compatible_deals',0)]:
            raw=self.completed();raw['candidate'][key]=value
            self.assert_closed(self.run_raw(raw),'error')
        with patch('research.analysis_contract.run_guarded',side_effect=OSError('runner unavailable')):
            self.assert_closed(analyze(self.request),'error')

    def test_delivery_recheck_discards_changed_decision_without_promoting_errors(self):
        ready=self.run_raw(self.completed())
        self.assert_closed(recheck_decision(ready,'changed'),'stale')
        self.assertIsNotNone(ready['candidate'])
        self.assertEqual(recheck_decision(ready,ready['source_information_key']),ready)
        error=self.run_raw({'status':'error'})
        self.assertEqual(recheck_decision(error,error['source_information_key']),error)

    def test_nonstring_selected_ids_are_invalid_before_hashing(self):
        bad=copy.deepcopy(self.request);bad['selected_hands'][1]=['AhAd']
        with patch('research.analysis_contract.run_guarded') as runner:
            self.assert_closed(analyze(bad),'invalid_input')
            runner.assert_not_called()

    def test_tree_limits_and_exact_root_action_labels_must_match(self):
        for field,value in [('public_nodes',20001),('joint_deals',10),('max_joint_combos',64),
                            ('bet_sizes',[50]),('future_raise_cap',2)]:
            raw=self.completed();raw['tree'][field]=value
            self.assert_closed(self.run_raw(raw),'error')
        raw=self.completed();raw['candidate']['actions'][-1]='RAISE 81'
        self.assert_closed(self.run_raw(raw),'error')
        raw=self.completed();raw['candidate']['actions'].reverse()
        self.assert_closed(self.run_raw(raw),'error')

    def test_root_actions_match_independent_built_tree_after_short_raises(self):
        from research.benchmark_midriver_ranges import scenarios
        from research.river_snapshot import build_river_from_snapshot
        for case in scenarios():
            if case['name'] not in ('short_closed_3','short_reopened_4','prior_allin_3'):continue
            request={k:case[k] for k in ('snapshot','selected_hands','input')}
            request['own_hand']=case['selected_hands'][case['snapshot']['actor_id']][0]
            game,_=build_river_from_snapshot(request['snapshot'],request['selected_hands'],**request['input'])
            self.assertEqual(expected_root_actions(request),list(game.root.actions))

    def test_real_worker_has_correct_probe_quality_identity_and_tree(self):
        # Native integration is checked separately where a compiler/library exists.
        # Use indexed training only inside the worker for this deterministic transport test.
        from research.custom_river import RiverGame
        original=RiverGame.train
        def indexed(game,iterations,method):return original(game,iterations,method='cfr_plus_indexed')
        with patch.object(RiverGame,'train',indexed),contextlib.redirect_stdout(io.StringIO()):
            raw=worker(self.request,3)
        self.assertEqual(raw['status'],'completed')
        self.assertEqual(raw['request_key'],digest(self.request))
        self.assertEqual(raw['candidate']['own_hand'],self.request['own_hand'])
        self.assertTrue(valid_quality(raw['metrics'],2,self.request['snapshot']['pot']))
        self.assertGreater(raw['tree']['public_nodes'],0)
        self.assertEqual(raw['tree']['future_raise_cap'],1)
        raw.update(wall_seconds=.2,sampled_peak_rss_mib=30.)
        with patch('research.analysis_contract.run_guarded',return_value=raw):
            result=analyze(self.request,ResearchLimits(iterations=3))
        # A small iteration count may fail quality; it must still be an explained decision.
        self.assertIn(result['status'],('ready','quality_rejected'))
        json.dumps(result,allow_nan=False)
