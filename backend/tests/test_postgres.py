"""Opt-in integration checks; use a disposable PostgreSQL database only.

POKER_TEST_DATABASE_URL is never populated from the application's production URL.
"""
import os
import unittest
from unittest.mock import patch

from app.api import hand as live, training as api
from app.services.database import DatabaseFailure
from app.services.room_repository import RoomRepository, RoomStorageError
from app.services.room_service import RoomCommand, RoomStore
from app.services.training_store import TrainingStore


@unittest.skipUnless(os.environ.get('POKER_TEST_DATABASE_URL'), 'Disposable PostgreSQL not configured')
class PostgresTests(unittest.TestCase):
    def setUp(self):
        self.url = os.environ['POKER_TEST_DATABASE_URL']
        self.rooms = RoomStore(self.url); self.rooms.open()
        self.training = TrainingStore(self.url); self.training.open()
        self.profile = self.training.create_profile()
        self.owner = self.profile['profile_id']
        self.old_store, self.old_state = api.store, live.current_state
        api.store = self.training
        live.current_state = live.engine.start_hand()

    def tearDown(self):
        api.store, live.current_state = self.old_store, self.old_state
        self.training.close(); self.rooms.close()

    def test_training_pagination_idempotence_and_reconnect(self):
        question = self.training.next_question(self.owner, 'call_price')
        request = api.ExerciseAnswer(question_id=question['question_id'], attempt_id='answer', percent=25)
        first = self.training.answer(self.owner, request)
        self.assertTrue(first['correct'])
        self.assertEqual(first, self.training.answer(self.owner, request))
        with self.assertRaises(ValueError):
            self.training.answer(self.owner, request.model_copy(update={'percent': 30}))
        state = live.current_state
        action = api.SavedAction(command_id='move', hand_id=state.hand_id,
                                 history_length=len(state.history), action='call')
        auth = 'Bearer ' + self.profile['token']
        from fastapi import Response
        result = api.save_action(action, Response(), auth)
        self.assertEqual(api.save_action(action, Response(), auth)['decision_id'], result['decision_id'])
        journal = self.training.decisions(self.owner)
        self.assertEqual(len(journal['items']), 1)
        self.assertEqual(self.training.decisions(self.owner, before=result['decision_id'])['items'], [])
        other = self.training.create_profile()['profile_id']
        self.assertEqual(self.training.decisions(other)['items'], [])
        with self.assertRaises(ValueError): self.training.question(other, question['question_id'])
        self.training.connection.raw.close()
        self.assertEqual(self.training.authenticate(self.profile['token']), self.owner)
        self.assertEqual(self.training.progress(self.owner)['attempts'], 1)
        self.training.close(); self.training = TrainingStore(self.url); self.training.open(); api.store = self.training
        self.assertEqual(self.training.decisions(self.owner), journal)

    def test_failed_write_rolls_back_and_next_transaction_succeeds(self):
        count = self.training.progress(self.owner)['questions']
        before = live.current_state.model_dump_json()
        original = self.training.connection.execute
        def fail_questions(sql, params=()):
            if 'INSERT INTO training_questions' in sql:
                return original('INSERT INTO missing_test_table VALUES (1)')
            return original(sql, params)
        request = api.SavedAction(command_id='failure', hand_id=live.current_state.hand_id,
                                 history_length=len(live.current_state.history), action='call')
        from fastapi import Response
        with patch.object(self.training.connection, 'execute', side_effect=fail_questions):
            with self.assertRaises(RoomStorageError):
                api.save_action(request, Response(), 'Bearer ' + self.profile['token'])
        self.assertEqual(live.current_state.model_dump_json(), before)
        self.assertEqual(self.training.progress(self.owner)['questions'], count)
        self.assertEqual(self.training.decisions(self.owner)['items'], [])
        self.assertIsNotNone(self.training.create_profile()['profile_id'])

    def test_rooms_archive_membership_and_restart(self):
        room, host = self.rooms.create('Host')
        guest = self.rooms.apply(room, lambda: room.join('Guest'), 'join')
        for member in room.seated: member.sockets.add(object())
        counter = 0
        def command(member, kind, **data):
            nonlocal counter
            counter += 1
            item = RoomCommand(command_id=str(counter), revision=room.revision, kind=kind, **data)
            self.rooms.apply(room, lambda: room.command(member, item), kind, item.command_id, member.player_id)
        for member in room.seated: command(member, 'ready', ready=True)
        command(host, 'start')
        current = next(member for member in room.seated if member.player_id == room.hand.current_player_id)
        command(current, 'action', action='fold', hand_id=room.hand.hand_id)
        history = self.rooms.repository.history_page(room.code, host.player_id)
        self.assertEqual(len(history['items']), 1)
        self.assertEqual(self.rooms.repository.history_page(room.code, 'outsider')['items'], [])
        cursor = history['items'][0]['cursor']
        self.assertEqual(self.rooms.repository.history_page(room.code, host.player_id, before=cursor)['items'], [])
        record = room.to_record()
        self.rooms.close(); self.rooms = RoomStore(self.url); self.rooms.open()
        restored = self.rooms.get(room.code)
        self.assertEqual(restored.to_record(), record)
        self.assertEqual(restored.authenticate(host.token).player_id, host.player_id)
        self.assertEqual(self.rooms.repository.history_page(room.code, host.player_id), history)
        rows = self.rooms.repository.connection.execute("SELECT relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='poker_private' AND c.relkind='r'").fetchall()
        self.assertEqual(len(rows), 7)
        self.assertTrue(all(row[0] for row in rows))
