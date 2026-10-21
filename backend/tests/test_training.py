import json
import math
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from fastapi import HTTPException, Response
from pydantic import ValidationError

from app.api import hand as live, training as api
from app.models.poker import ActionType
from app.services.room_repository import RoomRepository, RoomStorageError
from app.services.training_store import TrainingStore, question_data, starter_state


class TrainingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'training.sqlite3'
        self.rooms = RoomRepository(self.path); self.rooms.open()
        self.store = TrainingStore(self.path); self.store.open()
        self.profile = self.store.create_profile()
        self.owner = self.profile['profile_id']
        self.auth = 'Bearer ' + self.profile['token']
        self.old_store, self.old_state = api.store, live.current_state
        api.store = self.store
        live.current_state = live.engine.start_hand()

    def tearDown(self):
        api.store, live.current_state = self.old_store, self.old_state
        self.store.close(); self.rooms.close(); self.temp.cleanup()

    def action_request(self, action='call', amount=None, command_id='move'):
        state = live.current_state
        return api.SavedAction(command_id=command_id, hand_id=state.hand_id,
                               history_length=len(state.history), action=action, amount=amount)

    def move(self, request=None):
        return api.save_action(request or self.action_request(), Response(), self.auth)

    def answer(self, question, value=None, actions=None, attempt_id='attempt'):
        request = api.ExerciseAnswer(question_id=question['question_id'], attempt_id=attempt_id, percent=value, actions=actions)
        return self.store.answer(self.owner, request)

    def test_profiles_have_isolated_tokens_and_no_plaintext_token_in_database(self):
        other = self.store.create_profile()
        self.assertEqual(self.store.authenticate(self.profile['token']), self.owner)
        self.assertNotEqual(self.owner, other['profile_id'])
        for token in [None, '', 'invalid']:
            with self.assertRaises(PermissionError): self.store.authenticate(token)
        raw = self.store.connection.execute('SELECT token_hash FROM training_profiles WHERE profile_id=?', (self.owner,)).fetchone()[0]
        self.assertNotEqual(raw, self.profile['token'])
        with self.assertRaises(HTTPException) as error: api.profile(None)
        self.assertEqual(error.exception.status_code, 401)

    def test_starter_questions_hide_answers_and_opponent_cards(self):
        question = self.store.next_question(self.owner, 'legal_actions')
        self.assertIsNone(question['hand']['betting'])
        self.assertNotIn('answer', question)
        self.assertNotIn('expected', question)
        self.assertEqual(question['hand']['players'][1]['cards'], [])
        self.assertEqual(self.store.progress(self.owner)['questions'], 4)

    def test_normal_call_price_and_rounding_tolerance(self):
        question = self.store.next_question(self.owner, 'call_price')
        result = self.answer(question, 25.4)
        self.assertTrue(result['correct'])
        self.assertEqual(result['expected'], 25)
        self.assertIn('20 / (60 + 20)', result['explanation'])
        self.assertFalse(self.answer(question, 25.6, attempt_id='wrong')['correct'])

    def test_short_all_in_excludes_uncallable_overbet(self):
        question = self.store.next_question(self.owner, 'call_price')
        self.answer(question, 25)
        short = self.store.next_question(self.owner, 'call_price')
        self.assertEqual(short['context']['call_amount'], 20)
        self.assertEqual(short['context']['uncalled_return'], 80)
        result = self.answer(short, 33.3, attempt_id='short')
        self.assertTrue(result['correct'])
        self.assertAlmostEqual(result['expected'], 100 / 3)
        self.assertIn('80 uncallable chips', result['explanation'])

    def test_legal_actions_exact_set_and_short_all_in(self):
        question = self.store.next_question(self.owner, 'legal_actions')
        self.assertFalse(self.answer(question, actions=['call'], attempt_id='partial')['correct'])
        self.assertFalse(self.answer(question, actions=['fold','call','raise','raise'], attempt_id='duplicate')['correct'])
        result = self.answer(question, actions=['raise','call','fold'], attempt_id='all')
        self.assertTrue(result['correct'])
        short = self.store.next_question(self.owner, 'legal_actions')
        self.assertTrue(self.answer(short, actions=['fold','call'], attempt_id='short')['correct'])

    def test_failed_questions_repeat_first_and_progress_tracks_latest_answer(self):
        question = self.store.next_question(self.owner, 'call_price')
        self.answer(question, 50)
        self.assertEqual(self.store.next_question(self.owner, 'call_price')['question_id'], question['question_id'])
        self.answer(question, 25, attempt_id='fixed')
        self.assertNotEqual(self.store.next_question(self.owner, 'call_price')['question_id'], question['question_id'])
        stats = self.store.progress(self.owner)
        self.assertEqual(stats['attempts'], 2)
        self.assertEqual(stats['correct_attempts'], 1)
        self.assertEqual(stats['last_answer_correct'], 1)
        self.answer(question, 50, attempt_id='forgotten')
        self.assertEqual(self.store.progress(self.owner)['last_answer_correct'], 0)

    def test_attempt_retries_are_idempotent_and_changed_payload_is_rejected(self):
        question = self.store.next_question(self.owner, 'call_price')
        first = self.answer(question, 25)
        self.assertEqual(self.answer(question, 25), first)
        self.assertEqual(self.store.progress(self.owner)['attempts'], 1)
        with self.assertRaises(ValueError): self.answer(question, 30)

    def test_other_profile_cannot_read_or_answer_questions(self):
        question = self.store.next_question(self.owner, 'call_price')
        other = self.store.create_profile()['profile_id']
        with self.assertRaises(ValueError): self.store.question(other, question['question_id'])
        request = api.ExerciseAnswer(question_id=question['question_id'], attempt_id='foreign', percent=25)
        with self.assertRaises(ValueError): self.store.answer(other, request)
        self.assertEqual(self.store.progress(other)['attempts'], 0)

    def test_answers_validate_type_bounds_and_matching_answer_kind(self):
        question = self.store.next_question(self.owner, 'call_price')
        for value in [True, -1, 101, float('nan'), float('inf'), '25']:
            with self.assertRaises(ValidationError): api.ExerciseAnswer(question_id=question['question_id'], attempt_id='bad', percent=value)
        with self.assertRaises(ValueError): self.answer(question, actions=['fold'])
        with self.assertRaises(ValueError): self.answer(question, 25, actions=['fold'])

    def test_action_is_saved_with_original_snapshot_and_correct_privacy(self):
        original = live.current_state.model_copy(deep=True)
        result = self.move()
        journal = self.store.decisions(self.owner)['items']
        self.assertEqual(len(journal), 1)
        saved = journal[0]
        self.assertEqual(saved['hand']['history'], original.model_dump(mode='json')['history'])
        self.assertEqual(saved['hand']['players'][1]['cards'], [])
        self.assertNotIn('_deck', json.dumps(saved))
        self.assertNotIn(self.profile['token'], json.dumps(saved))
        self.assertEqual(result['state'].pot, 20)
        self.assertEqual(set(saved['exercises']), {'call_price','legal_actions'})
        self.assertEqual(self.store.progress(self.owner)['questions'], 6)

    def test_multiway_decision_creates_rules_exercise_without_single_pot_price(self):
        live.current_state = live.engine.start_hand(player_count=3)
        self.move()
        saved = self.store.decisions(self.owner)['items'][0]
        self.assertEqual(set(saved['exercises']), {'legal_actions'})
        self.assertFalse(saved['analysis']['call_ev_available'])
        self.assertEqual(self.store.progress(self.owner)['questions'], 5)

    def test_invalid_action_and_stale_state_do_not_create_records(self):
        before = live.current_state.model_dump_json()
        with self.assertRaises(HTTPException): self.move(self.action_request('check'))
        stale = self.action_request().model_copy(update={'history_length': 0})
        with self.assertRaises(HTTPException) as error: self.move(stale)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(live.current_state.model_dump_json(), before)
        self.assertEqual(self.store.decisions(self.owner)['items'], [])

    def test_saved_action_retry_does_not_move_chips_twice(self):
        request = self.action_request()
        first = self.move(request)
        state = live.current_state.model_dump_json()
        again = self.move(request)
        self.assertEqual(first['decision_id'], again['decision_id'])
        self.assertEqual(live.current_state.model_dump_json(), state)
        self.assertEqual(len(self.store.decisions(self.owner)['items']), 1)
        with self.assertRaises(HTTPException): self.move(request.model_copy(update={'action': ActionType.FOLD}))

    def test_write_failure_rolls_back_decision_exercises_and_live_action(self):
        original = live.current_state
        before = original.model_dump_json(); deck = list(original._deck)
        self.store.connection.execute("CREATE TRIGGER fail_training BEFORE INSERT ON training_questions BEGIN SELECT RAISE(ABORT,'write failure'); END")
        self.store.connection.commit()
        with self.assertRaises(RoomStorageError): self.move()
        self.assertIs(live.current_state, original)
        self.assertEqual(live.current_state.model_dump_json(), before)
        self.assertEqual(live.current_state._deck, deck)
        self.assertEqual(self.store.decisions(self.owner)['items'], [])
        self.assertEqual(self.store.progress(self.owner)['questions'], 4)

    def test_profile_progress_decisions_and_replay_guard_survive_restart(self):
        question = self.store.next_question(self.owner, 'call_price')
        self.answer(question, 25)
        request = self.action_request(); self.move(request)
        before = self.store.decisions(self.owner)
        self.store.close(); self.store = TrainingStore(self.path); self.store.open(); api.store = self.store
        self.assertEqual(self.store.authenticate(self.profile['token']), self.owner)
        self.assertEqual(self.store.progress(self.owner)['attempts'], 1)
        self.assertEqual(self.store.decisions(self.owner), before)
        self.move(request)
        live.current_state = None
        with self.assertRaises(HTTPException) as error: self.move(request)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(self.store.decisions(self.owner)['items']), 1)

    def test_concurrent_action_requests_commit_only_one_choice(self):
        requests = [self.action_request('call', command_id='call'), self.action_request('fold', command_id='fold')]
        def submit(request):
            try: self.move(request); return True
            except HTTPException: return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(submit, requests)), 1)
        self.assertEqual(len(self.store.decisions(self.owner)['items']), 1)

    def test_same_id_in_another_profile_does_not_return_private_journal(self):
        self.move()
        other = self.store.create_profile()['profile_id']
        self.assertEqual(self.store.decisions(other)['items'], [])
        self.assertIsNone(self.store.cached_decision(other, 'move', 'anything'))

    def test_raise_rights_context_is_available_without_answer_leakage(self):
        state = starter_state()
        state.acted_at_bet['hero'] = 10
        state.last_full_raise = 20
        public, expected = question_data(state, 'legal_actions')
        self.assertEqual(public['context']['hero_acted_at_bet'], 10)
        self.assertEqual(public['context']['last_full_raise'], 20)
        self.assertNotIn('raise', expected)
        self.assertNotIn('acted_at_bet', public['hand'])
        self.assertIsNone(public['hand']['betting'])

    def test_failed_answer_write_does_not_change_progress_or_cache_attempt(self):
        question = self.store.next_question(self.owner, 'call_price')
        self.store.connection.execute("CREATE TRIGGER fail_answer BEFORE INSERT ON training_attempts BEGIN SELECT RAISE(ABORT,'write failure'); END")
        self.store.connection.commit()
        with self.assertRaises(RoomStorageError): self.answer(question, 25)
        self.assertEqual(self.store.progress(self.owner)['attempts'], 0)
        self.store.connection.execute('DROP TRIGGER fail_answer'); self.store.connection.commit()
        self.assertTrue(self.answer(question, 25)['correct'])
        self.assertEqual(self.store.progress(self.owner)['attempts'], 1)

    def test_failed_profile_initialization_does_not_leave_partial_profile(self):
        count = self.store.connection.execute('SELECT count(*) FROM training_profiles').fetchone()[0]
        self.store.connection.execute("CREATE TRIGGER fail_profile_questions BEFORE INSERT ON training_questions BEGIN SELECT RAISE(ABORT,'write failure'); END")
        self.store.connection.commit()
        with self.assertRaises(RoomStorageError): self.store.create_profile()
        self.assertEqual(self.store.connection.execute('SELECT count(*) FROM training_profiles').fetchone()[0], count)

    def test_skipping_unseen_question_returns_another_without_creating_attempt(self):
        first = self.store.next_question(self.owner, 'call_price')
        second = self.store.next_question(self.owner, 'call_price', exclude=first['question_id'])
        self.assertNotEqual(first['question_id'], second['question_id'])
        self.assertEqual(self.store.progress(self.owner)['attempts'], 0)


if __name__ == '__main__': unittest.main()
