import copy
import json
import random
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from app.api import hand as live, training as training_api, river_lessons as api
from app.models.poker import ActionType
from app.services.poker_engine import PokerEngine
from app.services.room_repository import RoomRepository
from app.services.training_store import TrainingStore
from app.services.training_completion import observe_completed
from research.river_lessons import RiverLessons, LessonError
from research.history_river import source, assess
from backend.tests.test_river_lessons import TestExecutor


def save_river(store, owner, count=2):
    engine=PokerEngine()
    with patch('app.services.poker_engine.secrets.SystemRandom',return_value=random.Random(42+count)):
        state=engine.start_hand(player_count=count)
    saved=[]
    for _ in range(100):
        if state.result:
            return state,saved
        if state.current_player_id is None:
            state=engine.advance(state);continue
        options=state.betting.legal_actions
        action=ActionType.CHECK if ActionType.CHECK in options else ActionType.CALL
        if state.current_player_id=='hero' and state.street.value=='river':
            analysis=SimpleNamespace(hand_id=state.hand_id,street=state.street,recommended_action=action.value,
                coach_summary='Saved heuristic.',model_dump=lambda **kwargs:{'source':'heuristic'})
            record=store.save_decision(owner,state.hand_id+'-'+str(len(saved)),'{}',state,analysis,action,None)
            saved.append(record['decision_id'])
        state=engine.apply_action(state,state.current_player_id,action)
    raise AssertionError('Passive hand must end.')


class HistoryRiverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'test.sqlite3'
        self.rooms=RoomRepository(self.path);self.rooms.open()
        self.store=TrainingStore(self.path);self.store.open()
        self.owner=self.store.create_profile()['profile_id'];self.other=self.store.create_profile()['profile_id']
        self.executor=TestExecutor();self.lessons=RiverLessons(self.executor,store=self.store)

    def tearDown(self):
        self.store.close();self.rooms.close();self.temp.cleanup()

    def complete(self,count=2):
        state,ids=save_river(self.store,self.owner,count)
        self.assertTrue(ids);self.store.mark_hand_completed(self.owner,state)
        return state,ids[0]

    def test_completion_is_required_persistent_idempotent_and_owner_scoped(self):
        state,ids=save_river(self.store,self.owner)
        self.assertEqual(self.store.completed_river_decisions(self.owner)['items'],[])
        with self.assertRaises(LessonError):self.lessons.history_detail(self.owner,ids[0])
        self.store.mark_hand_completed(self.other,state)
        self.assertEqual(self.lessons.history(self.owner)['items'],[])
        self.store.mark_hand_completed(self.owner,state)
        before=self.lessons.history(self.owner)
        self.store.mark_hand_completed(self.owner,state)
        self.assertEqual(before,self.lessons.history(self.owner))
        self.assertEqual(self.lessons.history(self.other)['items'],[])
        with self.assertRaises(LessonError) as e:self.lessons.history_detail(self.other,ids[0])
        self.assertEqual(e.exception.status,404)
        self.store.close();self.store=TrainingStore(self.path);self.store.open();self.lessons.store=self.store
        self.assertEqual(before,self.lessons.history(self.owner))

    def test_saved_public_decision_supports_one_to_five_opponents_without_final_cards(self):
        for count in range(2,7):
            final,decision=self.complete(count)
            saved=self.store.completed_river_decision(self.owner,decision)
            self.assertTrue(all(not p['cards'] for p in saved['hand']['players'] if p['id']!='hero'))
            snapshot,hand,version,model=source(saved)
            first,request=assess(saved,snapshot,hand,version,model)
            self.assertTrue(first['supported'],first['reason'])
            self.assertEqual(first['lesson']['opponents'],count-1)
            self.assertLessEqual(first['joint_deals'],64)
            self.assertTrue(all(row['selected_combos']==2 and 0<row['weight_share']<1 for row in first['coverage']))
            poisoned=copy.deepcopy(saved)
            for player in poisoned['hand']['players']:
                if player['id']!='hero':player['cards']=final.players[0].model_dump(mode='json')['cards']
            poisoned['later_history']=[{'action':'raise','amount':99999}]
            poisoned['final_result']=final.result.model_dump(mode='json')
            snapshot2,hand2,version2,model2=source(poisoned)
            self.assertEqual((snapshot,hand,version,model),(snapshot2,hand2,version2,model2))
            self.assertNotIn('final_result',json.dumps(request))
            changed_own=copy.deepcopy(saved)
            # Opponent selections must not depend on which legal own hand is probed.
            alternate=next(p for p in snapshot['players'] if p['id']=='hero')['range'][0]['cards']
            changed_own['hand']['players'][0]['cards']=[{'rank':alternate[i],'suit':{'s':'spades','h':'hearts','d':'diamonds','c':'clubs'}[alternate[i+1]]} for i in (0,2)]
            *_,alternate_model=source(changed_own)
            self.assertEqual({k:v for k,v in model['selected_hands'].items() if k!='hero'}, {k:v for k,v in alternate_model['selected_hands'].items() if k!='hero'})

    def test_explicit_ranges_own_hand_collisions_and_tree_limits(self):
        _,decision=self.complete();saved=self.store.completed_river_decision(self.owner,decision)
        snapshot,hand,version,model=source(saved)
        for mutate,reason in [
            (lambda m:m['selected_hands'].pop('hero'),'HISTORY_SELECT_TWO_HANDS'),
            (lambda m:m['selected_hands'].__setitem__('hero',['AsAs','2c2c']),'HISTORY_INVALID_HANDS'),
            (lambda m:m['selected_hands'].__setitem__('hero',['AsKd','7h7d']),'HISTORY_OWN_HAND_REQUIRED'),
            (lambda m:m.update(bet_sizes=[10001]),'HISTORY_UNSUPPORTED_TREE')]:
            bad=copy.deepcopy(model);mutate(bad);assessment,request=assess(saved,snapshot,hand,version,bad)
            self.assertFalse(assessment['supported']);self.assertIsNone(request)
            self.assertIn(assessment['reason'],[reason,'HISTORY_INVALID_HANDS'])
        blocked=copy.deepcopy(model)
        blocker=hand[:2]
        blocked['selected_hands']['villain']=[r['cards'] for r in snapshot['players'][1]['range'] if blocker in (r['cards'][:2],r['cards'][2:])][:2]
        rejected,request=assess(saved,snapshot,hand,version,blocked)
        self.assertFalse(rejected['supported']);self.assertEqual(rejected['reason'],'HISTORY_CARD_COLLISIONS');self.assertIsNone(request)
        with self.assertRaises(LessonError) as e:self.lessons.submit_history(self.owner,decision,model,'0'*64)
        self.assertEqual(e.exception.status,409);self.assertFalse(self.executor.items)
        submitted=self.lessons.submit_history(self.owner,decision,model,version)
        self.assertEqual(submitted['version'],submitted['assessment']['version'])
        self.assertEqual(self.lessons.poll(self.owner,submitted['ticket_id'])['lesson_id'],f'decision-{decision}')
        changed=copy.deepcopy(model);changed['bet_sizes']=[snapshot['big_blind'],3*snapshot['big_blind']]
        second=self.lessons.submit_history(self.owner,decision,changed,version)
        self.assertNotEqual(submitted['version'],second['version'])
        self.assertNotEqual(submitted['ticket_id'],second['ticket_id'])
        self.assertEqual(self.executor.items[submitted['ticket_id']]['state'],'cancelled')

    def test_api_rejects_hidden_snapshots_resource_overrides_and_foreign_profiles(self):
        _,decision=self.complete();detail=self.lessons.history_detail(self.owner,decision)
        body={'version':detail['source_version'],**detail['model']}
        parsed=api.HistoryModelRequest(**body)
        for extra in ({'snapshot':{}},{'iterations':2000},{'max_nodes':50000},{'max_raises':True},{'bet_sizes':[True]},{'bet_sizes':[1,2,3]}):
            with self.assertRaises(ValidationError):api.HistoryModelRequest(**{**body,**extra})
        with patch.object(api.river_lessons,'service',return_value=self.lessons):
            binding=live.training_owner.set(None)
            try:
                with self.assertRaises(HTTPException) as e:api.history_detail(decision)
                self.assertEqual(e.exception.status_code,401)
            finally:live.training_owner.reset(binding)
            binding=live.training_owner.set(self.other)
            try:
                with self.assertRaises(HTTPException) as e:api.history_submit(decision,parsed)
                self.assertEqual(e.exception.status_code,404)
            finally:live.training_owner.reset(binding)
        with self.assertRaises(HTTPException):api.HistoryModelRequest.validate_sizes(api.HistoryModelRequest(**{**body,'bet_sizes':[10001]}))

    def test_completion_observer_retries_after_storage_failure_without_changing_game(self):
        final,ids=save_river(self.store,self.owner)
        with patch.object(training_api,'store',self.store):
            with patch.object(self.store,'mark_hand_completed',side_effect=RuntimeError('offline')):
                with self.assertLogs('app.services.training_completion',level='WARNING'):observe_completed(self.owner,final)
            self.assertEqual(self.store.completed_river_decisions(self.owner)['items'],[])
            observe_completed(self.owner,final)
            self.assertEqual(self.store.completed_river_decisions(self.owner)['items'][0]['decision_id'],ids[0])
        from app.services import training_completion
        training_completion._saved.pop((self.owner,final.hand_id),None)
        # The serialized route observes the final state of the bound profile as well.
        old=live.profile_states.get(self.owner)
        live.profile_states[self.owner]=(final,0)
        binding=live.training_owner.set(self.owner)
        try:
            with patch.object(training_api,'store',self.store),patch.object(self.store,'mark_hand_completed',wraps=self.store.mark_hand_completed) as call:
                self.assertEqual(live.read_state().hand_id,final.hand_id);live.read_state();call.assert_called_once()
        finally:
            live.training_owner.reset(binding)
            if old is None:live.profile_states.pop(self.owner,None)
            else:live.profile_states[self.owner]=old

    def test_history_pagination_and_no_fabricated_legacy_completion(self):
        for _ in range(3):self.complete()
        page=self.store.completed_river_decisions(self.owner,limit=2)
        self.assertEqual(len(page['items']),2);self.assertIsNotNone(page['next_cursor'])
        older=self.store.completed_river_decisions(self.owner,page['next_cursor'])
        self.assertEqual(len(older['items']),1)
        # An old payload without a source index is deliberately not guessed complete.
        self.store.connection.execute('DELETE FROM training_decision_sources WHERE decision_id=?',(older['items'][0]['decision_id'],));self.store.connection.commit()
        self.assertEqual(self.store.completed_river_decisions(self.owner,page['next_cursor'])['items'],[])
