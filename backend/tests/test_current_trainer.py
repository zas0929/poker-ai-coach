import copy
import json
import random
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from pydantic import ValidationError

from app.api import hand, trainer_solver as api
from app.models.poker import ActionType
from app.services import trainer_solver
from app.services.poker_engine import PokerEngine
from research.analysis_contract import ResearchLimits
from research.river_lessons import LessonError
from research.river_snapshot import build_river_from_snapshot, digest
from research.lesson_values import action_values
from research.trainer_river import TrainerRiver, prepare
from backend.tests.test_river_lessons import TestExecutor


def river(count=2):
    engine = PokerEngine()
    with patch('app.services.poker_engine.secrets.SystemRandom', return_value=random.Random(42+count)):
        state = engine.start_hand(player_count=count)
    for _ in range(100):
        if state.street.value == 'river' and state.current_player_id == 'hero':
            return state
        if state.result:
            raise AssertionError('Passive hand ended before hero river.')
        if state.current_player_id is None:
            engine.advance(state)
        else:
            engine.apply_action(state, state.current_player_id,
                                ActionType.CHECK if ActionType.CHECK in state.betting.legal_actions else ActionType.CALL)
    raise AssertionError('No river.')


def evidence(request):
    game, _ = build_river_from_snapshot(request['snapshot'], request['selected_hands'], **request['input'])
    policy = {k: [1/m]*m for k, m in game.action_counts.items()}
    own = request['own_hand']; actor = game.root.actor
    deals = [(d,w) for d,(h,w,_) in enumerate(game.deals) if h[actor] == own]
    values = action_values(game, policy, own); values['actor_id'] = 'hero'
    return {'status':'ready', 'request_key':digest(request),
            'source_information_key':request['snapshot']['information_key'],
            'candidate':{'actor_id':'hero','own_hand':own,'actions':list(game.root.actions),
                         'probabilities':policy[(actor,own,game.root.history)],
                         'compatible_deals':len(deals),'conditional_mass':sum(w for _,w in deals)},
            'action_values':values,'quality':{'passed':True,'value':.1,'gate':.5},
            'admission':{'offline_analysis_allowed':True,'live_advice_allowed':False}}


class CurrentTrainerTests(unittest.TestCase):
    def setUp(self):
        self.executor = TestExecutor()
        self.service = TrainerRiver(self.executor, ResearchLimits())
        self.state = river()
        self.assessment, self.request = prepare(trainer_solver.public_copy(self.state))
        self.assertIsNotNone(self.request, self.assessment)
        self.profiles = hand.profile_states.copy()
        self.local = hand.current_state
        self.binding = hand.training_owner.set(None)

    def tearDown(self):
        hand.profile_states.clear(); hand.profile_states.update(self.profiles)
        hand.current_state = self.local
        hand.training_owner.reset(self.binding)
        self.service.close()

    def call(self, owner, operation, *args):
        binding = hand.training_owner.set(owner)
        try:
            return operation(*args)
        finally:
            hand.training_owner.reset(binding)

    def put(self, owner, state):
        hand.profile_states[owner] = (state, hand.monotonic())

    def test_public_boundary_and_identity_ignore_opponent_cards_and_deck(self):
        poisoned = self.state.model_copy(deep=True)
        for p in poisoned.players:
            if p.id != 'hero': p.cards = poisoned.players[0].cards
        poisoned._deck.reverse()
        self.assertEqual(trainer_solver.position_text(self.state), trainer_solver.position_text(poisoned))
        clean = trainer_solver.public_copy(poisoned)
        self.assertFalse(clean._deck)
        self.assertTrue(all(not p.cards for p in clean.players if p.id != 'hero'))
        self.assertEqual(prepare(clean), (self.assessment,self.request))
        self.assertIsNone(prepare(poisoned)[1])
        self.assertNotIn('_deck', json.dumps(self.request))
        self.assertTrue(all('cards' not in p for p in self.request['snapshot']['players']))
        for mutate in (lambda s:setattr(s,'pot',s.pot+1),lambda s:setattr(s,'last_full_raise',s.last_full_raise+1),
                       lambda s:s.acted_at_bet.update(hero=999),lambda s:setattr(s.players[0],'stack',7)):
            changed = self.state.model_copy(deep=True); mutate(changed)
            self.assertNotEqual(trainer_solver.position_key(changed),trainer_solver.position_key(self.state))

    def test_model_preparation_one_to_five_opponents_uses_small_public_ranges(self):
        for count in range(2,7):
            assessment, request = prepare(trainer_solver.public_copy(river(count)))
            self.assertIsNotNone(request, assessment)
            self.assertEqual(len(assessment['model']['coverage']), count)
            self.assertTrue(all(r['selected_combos']==2 and 0<r['weight_share']<1 for r in assessment['model']['coverage']))
            self.assertLessEqual(len(request['selected_hands']),6)
            self.assertFalse(assessment['replaces_heuristic'])
        bad = self.state.model_copy(deep=True);bad.current_player_id='villain'
        self.assertIsNone(prepare(trainer_solver.public_copy(bad))[1])

    def test_cached_job_is_reused_but_old_client_cancel_does_not_cancel_new_lease(self):
        a = self.service.submit('alice','old',self.assessment,self.request)
        b = self.service.submit('alice','new',self.assessment,self.request)
        self.assertNotEqual(a['ticket_id'],b['ticket_id'])
        self.assertEqual(len(self.executor.items),1)
        self.service.cancel('alice',a['ticket_id'])
        self.assertEqual(self.service.poll('alice',b['ticket_id'],self.assessment['position_key'])['state'],'queued')
        with self.assertRaises(LessonError):self.service.cancel('alice',a['ticket_id'])
        internal = next(iter(self.executor.items))
        self.executor.items[internal].update(state='completed',result=evidence(self.request))
        ready = self.service.poll('alice',b['ticket_id'],self.assessment['position_key'])
        self.assertEqual(ready['state'],'ready')
        c = self.service.submit('alice','refresh',self.assessment,self.request)
        self.assertEqual(c['state'],'ready');self.assertEqual(len(self.executor.items),1)
        self.assertFalse(c['replaces_heuristic'])

    def test_mutation_revokes_completed_results_and_foreign_profiles_are_isolated(self):
        a = self.service.submit('alice','nonce',self.assessment,self.request)
        for method,args in ((self.service.poll,('bob',a['ticket_id'],self.assessment['position_key'])),
                            (self.service.cancel,('bob',a['ticket_id']))):
            with self.assertRaises(LessonError) as e:method(*args)
            self.assertEqual(e.exception.status,404)
        internal = next(iter(self.executor.items))
        self.executor.items[internal].update(state='completed',result=evidence(self.request))
        self.service.observe('alice','f'*64)
        stale=self.service.poll('alice',a['ticket_id'],'f'*64)
        self.assertEqual(stale['state'],'stale');self.assertIsNone(stale['actions'])

    def test_queue_and_lease_capacity_are_bounded(self):
        self.executor.full=True
        busy=self.service.submit('alice','n',self.assessment,self.request)
        self.assertEqual(busy['state'],'busy');self.assertFalse(self.service.owners)
        self.executor.full=False
        for i in range(8):self.service.submit('alice',str(i),self.assessment,self.request)
        self.assertEqual(self.service.submit('alice','ninth',self.assessment,self.request)['state'],'busy')
        self.assertEqual(len(self.executor.items),1)

    def test_bad_worker_identity_quality_ev_and_budget_never_publish_actions(self):
        job=self.service.submit('alice','n',self.assessment,self.request)
        internal=next(iter(self.executor.items)); good=evidence(self.request)
        for change in (lambda r:r.update(request_key='0'*64),lambda r:r['quality'].update(value=100),
                       lambda r:r['action_values']['ev_chips'].__setitem__(0,float('nan')),
                       lambda r:r.update(status='budget_exceeded', reasons=[{'code':'TIME_BUDGET_EXCEEDED'}])):
            bad=copy.deepcopy(good);change(bad)
            self.executor.items[internal].update(state='completed',result=bad)
            view=self.service.poll('alice',job['ticket_id'],self.assessment['position_key'])
            self.assertNotEqual(view['state'],'ready');self.assertIsNone(view['actions'])

    def test_api_server_position_only_double_checks_change_and_cancels_on_action(self):
        self.put('alice',self.state)
        body=api.CurrentModelRequest(position=trainer_solver.position_text(self.state),nonce='n')
        with patch.object(trainer_solver,'service',return_value=self.service), patch.object(trainer_solver,'_service',self.service):
            with self.assertRaises(HTTPException) as e:api.submit(body)
            self.assertEqual(e.exception.status_code,401)
            job=self.call('alice',api.submit,body)
            with self.assertRaises(HTTPException) as e:self.call('bob',api.poll,job['ticket_id'])
            self.assertEqual(e.exception.status_code,404)
            self.call('alice',hand.apply_action, __import__('app.models.poker',fromlist=['PlayerActionRequest']).PlayerActionRequest(action=ActionType.CHECK))
            stale=self.call('alice',api.poll,job['ticket_id'])
            self.assertEqual(stale['state'],'stale');self.assertIsNone(stale['actions'])
            with self.assertRaises(HTTPException) as e:self.call('alice',api.submit,body)
            self.assertEqual(e.exception.status_code,409)
        for extra in ({'snapshot':{}},{'iterations':1000}):
            with self.assertRaises(ValidationError):api.CurrentModelRequest(**{**body.model_dump(),**extra})
