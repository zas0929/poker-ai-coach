"""Current-turn contract, shared-queue and training API regression checks."""
import copy
from contextlib import redirect_stdout
import io
import json
import time
from threading import Event
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from app.api import hand, trainer_solver as api
from app.models.poker import ActionType, PlayerActionRequest
from app.services import trainer_solver
from research import turn_analysis
from research.analysis_contract import ResearchLimits
from research.analysis_dispatch import analyze, protocol_for
from research.river_lessons import LessonError, RiverLessons
from research.shadow_executor import ShadowExecutor
from research.trainer_current import prepare, valid_turn_result
from research.trainer_river import TrainerRiver
from research.river_snapshot import combo_key
from backend.tests.test_river_lessons import TestExecutor
from backend.tests.test_turn_snapshot import turn


class CurrentTurnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = turn(2)
        cls.assessment, cls.request = prepare(trainer_solver.public_copy(cls.state))
        cls.limits = ResearchLimits(iterations=100)
        with redirect_stdout(io.StringIO()):
            cls.raw = turn_analysis.worker(cls.request,100)
        # Admission unit tests use synthetic runner evidence; a separate test below
        # executes the real guarded process and actual shared queue.
        cls.raw.update(wall_seconds=1.,sampled_peak_rss_mib=40.,peak_rss_mib=40.)

    def admitted(self,raw=None):
        with patch.object(turn_analysis,'run_guarded',return_value=copy.deepcopy(self.raw if raw is None else raw)):
            return turn_analysis.analyze(self.request,self.limits)

    def test_public_preparation_for_one_to_five_opponents_without_hidden_or_future_data(self):
        for count in range(2,7):
            state=turn(count); clean=trainer_solver.public_copy(state)
            assessment,request=prepare(clean)
            self.assertIsNotNone(request,assessment)
            self.assertEqual(assessment['contract_version'],'trainer_current_turn_v1')
            self.assertEqual(len(assessment['model']['coverage']),count)
            self.assertTrue(all(r['selected_combos']==(8 if count==2 else 4 if count==3 else 2) for r in assessment['model']['coverage']))
            self.assertEqual(request['input']['river_max_raises'],0)
            self.assertTrue(all(a['street']!='river' for a in request['snapshot']['history']))
            poisoned=state.model_copy(deep=True)
            for p in poisoned.players:
                if p.id!='hero':p.cards=state.players[0].cards
            poisoned._deck.reverse()
            self.assertEqual(prepare(trainer_solver.public_copy(poisoned)),(assessment,request))
            self.assertIsNone(prepare(poisoned)[1])

    def test_actual_native_evidence_admits_decision_relative_ev_and_all_river_model(self):
        result=self.admitted()
        self.assertEqual(result['status'],'ready',result['reasons'])
        self.assertTrue(valid_turn_result(result,self.request,self.limits))
        self.assertEqual(result['action_values']['sunk_chips'],self.state.contributions['hero'])
        self.assertEqual(result['candidate']['actions'],turn_analysis.expected_root_actions(self.request))
        self.assertFalse(result['admission']['live_advice_allowed'])

    def test_resource_identity_tree_quality_and_values_fail_closed(self):
        changes=(
            lambda r:r.update(wall_seconds=11),
            lambda r:r.update(peak_rss_mib=129),
            lambda r:r.pop('sampled_peak_rss_mib'),
            lambda r:r.update(request_key='0'*64),
            lambda r:r.update(iterations=99),
            lambda r:r['provenance'].update(engine_version='river'),
            lambda r:r['tree'].update(river_max_raises=1),
            lambda r:r['tree'].update(joint_river_outcomes=9999),
            lambda r:r['metrics']['unilateral_gains'].__setitem__(0,999),
            lambda r:r['candidate'].update(actions=['BET 999999']),
            lambda r:r['action_values']['ev_chips'].__setitem__(0,float('nan')),
            lambda r:r['action_values']['gap_to_best_chips'].__setitem__(0,999),
            lambda r:r['metadata'].update(source_information_key='0'*64),
        )
        for change in changes:
            raw=copy.deepcopy(self.raw);change(raw)
            result=self.admitted(raw)
            self.assertNotEqual(result['status'],'ready',result)
            self.assertIsNone(result['candidate'])
            self.assertTrue(result['fallback']['retain_current_advice'])

    def test_short_opening_allin_remains_legal_below_the_big_blind(self):
        state=self.state.model_copy(deep=True)
        for player in state.players:player.stack=1
        from app.services.poker_engine import PokerEngine
        PokerEngine()._refresh_betting(state)
        assessment,request=prepare(trainer_solver.public_copy(state))
        self.assertIsNotNone(request,assessment)
        self.assertGreaterEqual(request['input']['turn_bet_sizes'][0],state.big_blind)
        self.assertEqual(turn_analysis.expected_root_actions(request),['CHECK','BET 1'])
        with redirect_stdout(io.StringIO()):
            raw=turn_analysis.worker(request,10)
        self.assertEqual(raw['status'],'completed')
        self.assertEqual(raw['candidate']['actions'],['CHECK','BET 1'])

    def test_known_hand_without_compatible_opponent_subset_is_an_explicit_refusal(self):
        request=copy.deepcopy(self.request)
        own=set(combo_key(request['own_hand']))
        alternative=next(h for h in request['selected_hands']['hero'] if h != request['own_hand'])
        blocked=set(combo_key(alternative))
        opponent=next(p for p in request['snapshot']['players'] if p['id']!='hero')
        choices=[r['cards'] for r in opponent['range'] if set(combo_key(r['cards'])) & own
                 and not set(combo_key(r['cards'])) & blocked]
        self.assertGreaterEqual(len(choices),2)
        request['selected_hands'][opponent['id']]=choices[:2]
        with redirect_stdout(io.StringIO()):
            raw=turn_analysis.worker(request,10)
        self.assertEqual(raw['status'],'invalid_probe')
        with patch.object(turn_analysis,'run_guarded',return_value=raw):
            result=turn_analysis.analyze(request,self.limits)
        self.assertEqual(result['reasons'][0]['code'],'UNSUPPORTED_OWN_HAND')
        self.assertIsNone(result['candidate'])

    def test_budget_and_cancellation_never_expose_partial_actions(self):
        for status in ('timed_out','memory_exceeded','model_budget_exceeded','cancelled','rejected','provider_unavailable'):
            result=self.admitted({'status':status})
            self.assertNotEqual(result['status'],'ready');self.assertIsNone(result['candidate'])
        stop=Event();stop.set()
        result=turn_analysis.analyze(self.request,self.limits,cancel_event=stop)
        self.assertEqual(result['status'],'cancelled')
        self.assertIsNone(result['candidate'])

    def test_bad_public_requests_are_rejected_before_worker_launch(self):
        mutations=(
            lambda r:r['snapshot'].update(deck=['As']),
            lambda r:r['input'].update(max_work=6000001),
            lambda r:r['input'].update(turn_max_raises=True),
            lambda r:r['input'].update(river_raise_sizes=[1,2,3]),
            lambda r:r.update(own_hand='AsAs'),
            lambda r:r['snapshot'].update(street='river'),
        )
        for change in mutations:
            request=copy.deepcopy(self.request);change(request)
            with patch.object(turn_analysis,'run_guarded') as worker:
                result=turn_analysis.analyze(request,self.limits)
            self.assertEqual(result['status'],'invalid_input');worker.assert_not_called()

    def test_delivery_rejects_wrong_street_contract_and_missing_resource_evidence(self):
        result=self.admitted()
        for change in (
                lambda r:r.update(contract_version=1),
                lambda r:r['quality'].update(value=0),
                lambda r:r['timing'].update(wall_seconds=20),
                lambda r:r.pop('timing'),
                lambda r:r['model']['tree'].update(turn_max_raises=0)):
            bad=copy.deepcopy(result);change(bad)
            self.assertFalse(valid_turn_result(bad,self.request,self.limits))

    def test_turn_reuses_leases_and_completed_result_but_revokes_on_river_change(self):
        executor=TestExecutor();service=TrainerRiver(executor,ResearchLimits(iterations=300))
        try:
            old=service.submit('alice','old',self.assessment,self.request)
            new=service.submit('alice','new',self.assessment,self.request)
            internal=next(iter(executor.items))
            self.assertEqual(len(executor.items),1)
            executor.items[internal].update(state='completed',result=self.admitted())
            service.cancel('alice',old['ticket_id'])
            ready=service.poll('alice',new['ticket_id'],self.assessment['position_key'])
            self.assertEqual(ready['state'],'ready')
            self.assertEqual(service.owners['alice']['limits'].iterations,100)
            with self.assertRaises(LessonError):service.poll('bob',new['ticket_id'],self.assessment['position_key'])
            service.observe('alice','f'*64)
            stale=service.poll('alice',new['ticket_id'],'f'*64)
            self.assertEqual(stale['state'],'stale');self.assertIsNone(stale['actions'])
        finally:service.close()

    def test_shared_single_worker_handles_real_turn_and_river_without_contract_crossing(self):
        with ShadowExecutor(max_pending=2,analyzer=analyze,protocol_for=protocol_for) as executor:
            for malformed in (None,{'snapshot':[]},{'snapshot':None}):
                self.assertIsNone(executor.submit('invalid',malformed,self.limits)['ticket_id'])
            lessons=RiverLessons(executor)
            river=lessons.examples['river-1']['request']
            tickets=[executor.submit('turn',self.request,self.limits),executor.submit('river',river,self.limits)]
            self.assertEqual(executor.stats()['active']+executor.stats()['pending'],2)
            start=time.monotonic()
            while any(executor.poll(t['ticket_id'])['state'] in ('queued','running') for t in tickets):
                self.assertLess(time.monotonic()-start,20)
                time.sleep(.02)
            results=[executor.poll(t['ticket_id'])['result'] for t in tickets]
            self.assertEqual([r['status'] for r in results],['ready','ready'])
            self.assertEqual([r['contract_version'] for r in results],['bounded_current_turn_v3',1])
            self.assertTrue(valid_turn_result(results[0],self.request,self.limits))

    def test_current_turn_api_binds_profile_position_and_cancels_when_player_acts(self):
        executor=TestExecutor();service=TrainerRiver(executor,ResearchLimits())
        profiles=hand.profile_states.copy();local=hand.current_state;binding=hand.training_owner.set('turn-alice')
        try:
            hand.profile_states['turn-alice']=(self.state.model_copy(deep=True),hand.monotonic())
            body=api.CurrentModelRequest(position=trainer_solver.position_text(self.state),nonce='turn')
            with patch.object(trainer_solver,'service',return_value=service),patch.object(trainer_solver,'_service',service):
                job=api.submit(body);self.assertEqual(job['contract_version'],'trainer_current_turn_v1')
                hand.apply_action(PlayerActionRequest(action=ActionType.CHECK))
                stale=api.poll(job['ticket_id'])
                self.assertEqual(stale['state'],'stale');self.assertIsNone(stale['actions'])
                with self.assertRaises(HTTPException) as error:api.submit(body)
                self.assertEqual(error.exception.status_code,409)
        finally:
            hand.profile_states.clear();hand.profile_states.update(profiles)
            hand.current_state=local;hand.training_owner.reset(binding);service.close()
