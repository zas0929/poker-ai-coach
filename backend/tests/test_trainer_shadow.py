import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch
from app.api import hand
from app.models.poker import ActionType,PlayerActionRequest
from app.services import trainer_shadow
from app.services.decision_engine import DecisionEngine
from app.services.solver_snapshot import prepare_solver_snapshot,card_text
from research.river_reference import cards
from research.trainer_shadow_bridge import TrainerShadowBridge,public_state


def fixture():
    engine=hand.PokerEngine();state=engine.start_hand(player_count=2)
    state.players[0].cards=cards('AhAd');state.players[1].cards=cards('KhKd')
    board='2c4d7h9sJc';used={'Ah','Ad','Kh','Kd',*[board[i:i+2] for i in range(0,10,2)]}
    from app.services.solver_snapshot import card_text
    state._deck=[c for c in engine._create_deck() if card_text(c) not in used]+list(reversed(cards(board)))
    while state.street.value!='river':
        if state.current_player_id is None:engine.advance(state)
        else:engine.apply_action(state,state.current_player_id,ActionType.CALL if state.betting.call_amount else ActionType.CHECK)
    engine.apply_action(state,state.current_player_id,ActionType.CHECK)
    assert state.current_player_id=='hero'
    snapshot=prepare_solver_snapshot(state)
    picks={'hero':['AhAd','3h3d'],'villain':['KhKd','5h5d']}
    selected={p['id']:[next(row['cards'] for row in p['range'] if set((row['cards'][:2],row['cards'][2:]))==set((t[:2],t[2:]))) for t in picks[p['id']]] for p in snapshot['players']}
    baseline=DecisionEngine().analyze(state)
    plan={'version':1,'decisions':{snapshot['information_key']:{'selected_hands':selected,
          'input':{'bet_sizes':[baseline.recommended_amount or 13,40],'raise_sizes':[80],'max_raises':1,'utility_storage':'compact'}}}}
    return state,snapshot,plan,baseline


def until(check):
    deadline=time.monotonic()+4
    while time.monotonic()<deadline:
        if check():return
        time.sleep(.005)
    raise AssertionError('Missing bridge transition')


class FakeExecutor:
    def __init__(self):self.requests=[];self.closed=False;self.rows={};self.advanced=[]
    def submit(self,context,request,limits):
        tid=str(len(self.requests)+1);self.requests.append(copy.deepcopy(request))
        self.rows[tid]={'state':'running','result':None};return {'ticket_id':tid,'job_id':'job-'+tid,'status':'queued'}
    def advance(self,context,key):self.advanced.append((context,key))
    def poll(self,tid):return self.rows[tid]
    def close(self):self.closed=True


class TrainerShadowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.state,cls.snapshot,cls.plan,cls.baseline=fixture()
    def setUp(self):
        self.old_state=hand.current_state;self.old_bridge=trainer_shadow._bridge
        self.token=hand.training_owner.set(None);trainer_shadow._bridge=None
        hand.current_state=self.state.model_copy(deep=True)
    def tearDown(self):
        trainer_shadow.stop_local_shadow();trainer_shadow._bridge=self.old_bridge
        hand.current_state=self.old_state;hand.training_owner.reset(self.token)

    def test_disabled_import_has_no_research_dependencies_or_threads(self):
        env={**os.environ,'POKER_LOCAL_TRAINER_SHADOW':'0'}
        script="from app.services import trainer_shadow; import sys; assert not trainer_shadow.start_local_shadow(); assert not any(k.startswith('research.') for k in sys.modules)"
        completed=subprocess.run([sys.executable,'-c',script],env=env,capture_output=True,text=True,timeout=5)
        self.assertEqual(completed.returncode,0,completed.stderr)
        with patch('research.trainer_shadow_bridge.TrainerShadowBridge') as factory,patch.dict(os.environ,env):
            self.assertFalse(trainer_shadow.start_local_shadow());factory.assert_not_called()

    def test_preparation_is_off_route_and_action_discards_stale_preparation(self):
        entered=Event();release=Event();fake=FakeExecutor();seen=[]
        def prepare(state):
            seen.append(state);entered.set();release.wait(3)
            return prepare_solver_snapshot(state)
        bridge=TrainerShadowBridge(self.plan,executor=fake,prepare=prepare);trainer_shadow._bridge=bridge
        try:
            with patch.object(hand.decision_engine,'analyze',return_value=self.baseline):
                answer=hand.analyze_hand()
            self.assertIs(answer,self.baseline)
            self.assertTrue(entered.wait(2));self.assertFalse(release.is_set())
            self.assertTrue(all(not p.cards for p in seen[0].players if p.id!='hero'))
            self.assertEqual(seen[0]._deck,[]);self.assertEqual(seen[0].notes,[])
            hand.apply_action(PlayerActionRequest(player_id='hero',action=ActionType.CHECK))
            release.set()
            until(lambda:any(e.get('code')=='STALE_PREPARATION' for e in bridge.events()))
            self.assertEqual(fake.requests,[])
        finally:release.set()

    def test_exact_plan_comparison_and_repeat_hint_does_not_requeue(self):
        fake=FakeExecutor();bridge=TrainerShadowBridge(self.plan,executor=fake);trainer_shadow._bridge=bridge
        with patch.object(hand.decision_engine,'analyze',return_value=self.baseline):
            hand.analyze_hand();until(lambda:len(fake.requests)==1)
            hand.analyze_hand()
        req=fake.requests[0]
        self.assertEqual(req['snapshot'],self.snapshot)
        self.assertIn(req['own_hand'],req['selected_hands']['hero'])
        label=self.baseline.recommended_action.upper()+' '+str(self.baseline.recommended_amount)
        fake.rows['1']={'state':'completed','result':{'status':'ready','source_information_key':self.snapshot['information_key'],
                       'quality':{'value':.01},'candidate':{'actions':['CHECK',label],'probabilities':[.2,.8]}}}
        until(lambda:any(e['event']=='comparison' for e in bridge.events()))
        comparison=next(e for e in bridge.events() if e['event']=='comparison')
        self.assertTrue(comparison['represented_exactly']);self.assertTrue(comparison['matches_most_likely'])
        self.assertFalse(comparison['live_advice_allowed'])
        self.assertNotIn('own_hand',json.dumps(bridge.events()))
        self.assertEqual(len(fake.requests),1)

    def test_explicit_policy_plan_handles_unlisted_snapshot_and_retains_exact_size(self):
        path=Path(__file__).parents[1]/'research/config/local-shadow-policy.json'
        fake=FakeExecutor();bridge=TrainerShadowBridge(json.loads(path.read_text()),executor=fake)
        try:
            bridge.observe('alice',self.state);bridge.offer('alice',self.state,self.baseline)
            until(lambda:len(fake.requests)==1)
            req=fake.requests[0]
            self.assertEqual(req['snapshot'],self.snapshot)
            self.assertEqual(len(req['selected_hands']['hero']),3)
            self.assertIn(req['own_hand'],req['selected_hands']['hero'])
            self.assertIn(self.baseline.recommended_amount,req['input']['bet_sizes'])
            submitted=next(e for e in bridge.events() if e['event']=='submitted')
            self.assertEqual(submitted['selection_policy'],'anchored_public_subset_v1')
            self.assertIsNotNone(submitted['selected_key'])
        finally:bridge.close()

    def test_no_plan_and_missing_own_hand_are_explained_without_solving(self):
        for plan,code in [({'version':1,'decisions':{}},'NO_EXPLICIT_PLAN'),
                          (copy.deepcopy(self.plan),'OWN_HAND_NOT_SELECTED')]:
            if code=='OWN_HAND_NOT_SELECTED':plan['decisions'][self.snapshot['information_key']]['selected_hands']['hero']=['3h3d']
            fake=FakeExecutor();bridge=TrainerShadowBridge(plan,executor=fake)
            try:
                bridge.observe('alice',self.state);bridge.offer('alice',self.state,self.baseline)
                until(lambda:any(e.get('code')==code for e in bridge.events()))
                self.assertEqual(fake.requests,[])
            finally:bridge.close()

    def test_profiles_and_stale_hints_are_independent(self):
        fake=FakeExecutor();bridge=TrainerShadowBridge(self.plan,executor=fake)
        try:
            bridge.observe('alice',self.state);bridge.observe('bob',self.state)
            bridge.offer('alice',self.state,self.baseline);bridge.offer('bob',self.state,self.baseline)
            until(lambda:len(fake.requests)==2)
            changed=self.state.model_copy(deep=True);changed.hand_id='next-hand'
            bridge.observe('alice',changed)
            self.assertFalse(bridge.offer('alice',self.state,self.baseline))
            self.assertFalse(bridge.offer('bob',self.state,self.baseline)) # same revision already offered
            self.assertEqual(bridge.stats()['contexts'],2)
            contexts={e['context_key'] for e in bridge.events() if e['event']=='submitted'}
            self.assertEqual(len(contexts),2)
        finally:bridge.close()

    def test_api_owner_binding_keeps_comparisons_separate(self):
        fake=FakeExecutor();bridge=TrainerShadowBridge(self.plan,executor=fake);trainer_shadow._bridge=bridge
        saved=hand.profile_states.copy()
        try:
            for owner in ('alice','bob'):
                hand.profile_states[owner]=(self.state.model_copy(deep=True),hand.monotonic())
                token=hand.training_owner.set(owner)
                try:
                    with patch.object(hand.decision_engine,'analyze',return_value=self.baseline):hand.analyze_hand()
                finally:hand.training_owner.reset(token)
            until(lambda:len(fake.requests)==2)
            token=hand.training_owner.set('alice')
            try:hand.apply_action(PlayerActionRequest(action=ActionType.CHECK))
            finally:hand.training_owner.reset(token)
            for tid in fake.rows:
                label=self.baseline.recommended_action.upper()+' '+str(self.baseline.recommended_amount)
                fake.rows[tid]={'state':'completed','result':{'status':'ready','source_information_key':self.snapshot['information_key'],
                      'quality':{'value':.01},'candidate':{'actions':['CHECK',label],'probabilities':[.2,.8]}}}
            until(lambda:any(e['event']=='comparison' for e in bridge.events()))
            comparisons=[e for e in bridge.events() if e['event']=='comparison']
            self.assertEqual(len(comparisons),1)
            self.assertEqual(comparisons[0]['context_key'],bridge._context('bob'))
        finally:
            hand.profile_states.clear();hand.profile_states.update(saved)

    def test_application_lifespan_starts_and_stops_local_service(self):
        import asyncio
        import app.main as application
        async def timers():await asyncio.Event().wait()
        async def exercise():
            async with application.lifespan(None):start.assert_called_once()
        with patch.object(application.store,'open'),patch.object(application.store,'close'),\
             patch.object(application.training_store,'open'),patch.object(application.training_store,'close'),\
             patch.object(application.store,'run_timers',timers),\
             patch.object(application,'start_local_shadow') as start,\
             patch.object(application,'stop_local_shadow') as stop:
            loop=asyncio.new_event_loop()
            try:loop.run_until_complete(exercise())
            finally:loop.close()
            stop.assert_called_once()

    def test_private_opponents_notes_and_deck_do_not_change_revision(self):
        other=self.state.model_copy(deep=True)
        other.players[1].cards=cards('QsQh');other.notes=['secret'];other._deck.reverse()
        self.assertEqual(public_state(self.state),public_state(other))
        self.assertNotIn('Kh',json.dumps(public_state(self.state)))

    def test_preparation_and_context_capacity_do_not_expand(self):
        release=Event();entered=Event();fake=FakeExecutor()
        def prepare(state):
            entered.set();release.wait(3);return prepare_solver_snapshot(state)
        bridge=TrainerShadowBridge(self.plan,executor=fake,prepare=prepare,max_contexts=3,max_pending=1)
        try:
            bridge.observe('a',self.state);bridge.offer('a',self.state,self.baseline)
            self.assertTrue(entered.wait(2))
            bridge.observe('b',self.state);self.assertTrue(bridge.offer('b',self.state,self.baseline))
            bridge.observe('c',self.state);self.assertFalse(bridge.offer('c',self.state,self.baseline))
            self.assertTrue(bridge.observe('d',self.state)) # idle c can be evicted
            self.assertEqual(bridge.stats()['pending_preparations'],1)
            self.assertEqual(bridge.stats()['contexts'],3)
            release.set();until(lambda:len(fake.requests)==2)
            bridge.observe('c',self.state);bridge.offer('c',self.state,self.baseline)
            until(lambda:len(fake.requests)==3)
            self.assertFalse(bridge.observe('d',self.state)) # every context now has a running ticket
            codes={e.get('code') for e in bridge.events()}
            self.assertIn('CONTEXT_CAPACITY',codes);self.assertIn('PREPARATION_QUEUE_FULL',codes)
        finally:release.set();bridge.close()

    def test_local_flag_requires_valid_plan_and_shutdown_closes_bridge(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'plan.json';path.write_text(json.dumps({'version':2}))
            env={'POKER_LOCAL_TRAINER_SHADOW':'1','POKER_LOCAL_TRAINER_SHADOW_PLAN':str(path)}
            with patch.dict(os.environ,env):
                self.assertFalse(trainer_shadow.start_local_shadow())
                path.write_text(json.dumps(self.plan))
                self.assertTrue(trainer_shadow.start_local_shadow())
                bridge=trainer_shadow._bridge
                trainer_shadow.stop_local_shadow();self.assertTrue(bridge.stats()['closed'])
                self.assertIsNone(trainer_shadow._bridge)

    def test_hook_errors_do_not_change_existing_hint_or_action(self):
        class Broken:
            def observe(self,*a):raise RuntimeError('secret')
            def offer(self,*a):raise RuntimeError('secret')
            def close(self):pass
        trainer_shadow._bridge=Broken()
        with patch.object(hand.decision_engine,'analyze',return_value=self.baseline):
            self.assertIs(hand.analyze_hand(),self.baseline)
        self.assertIsNotNone(hand.apply_action(PlayerActionRequest(action=ActionType.CHECK)))
