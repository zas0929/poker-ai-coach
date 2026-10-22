import asyncio
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from pydantic import ValidationError
from app.models.poker import ActionType
from app.services.room_repository import RoomStorageError
from app.services.room_service import RoomCommand, RoomSettings, RoomStore


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'private' / 'poker.sqlite3'
        self.store = RoomStore(self.path)
        self.store.open()
        self.room, self.host = self.store.create('Host', settings=RoomSettings(starting_stack=1000, small_blind=5, big_blind=10, auto_deal=False))
        self.guest = self.store.apply(self.room, lambda: self.room.join('Guest'), 'join')
        self.counter = 0
        self.connect()

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def connect(self):
        for member in self.room.seated:
            member.sockets.add(object())

    def command(self, member, kind, **data):
        self.counter += 1
        command = RoomCommand(command_id=str(self.counter), revision=self.room.revision, kind=kind, **data)
        self.store.apply(self.room, lambda: self.room.command(member, command), kind, command.command_id, member.player_id)
        return command

    def start(self):
        for member in self.room.seated:
            self.command(member, 'ready', ready=True)
        self.command(self.host, 'start')

    def restart(self):
        code, host_token, guest_token = self.room.code, self.host.token, self.guest.token
        self.store.close()
        self.store = RoomStore(self.path)
        self.store.open()
        self.room = self.store.get(code)
        self.host, self.guest = self.room.authenticate(host_token), self.room.authenticate(guest_token)

    def fail_writes(self):
        self.store.repository.connection.execute('''CREATE TRIGGER fail_event BEFORE INSERT ON room_events
            BEGIN SELECT RAISE(ABORT, 'test unavailable disk'); END''')
        self.store.repository.connection.commit()

    def test_settings_authority_validation_and_readiness_reset(self):
        self.command(self.host, 'ready', ready=True)
        settings = dict(starting_stack=2000, small_blind=10, big_blind=20, turn_seconds=45, auto_deal=False)
        with self.assertRaises(ValueError):
            self.command(self.guest, 'settings', settings=settings)
        self.command(self.host, 'settings', settings=settings)
        self.assertTrue(all(m.stack == 1000 for m in self.room.seated))
        self.restart()
        self.assertEqual(self.room.settings.model_dump(), settings)
        for invalid in [dict(big_blind=1), dict(starting_stack=100, big_blind=100), dict(turn_seconds=0), dict(small_blind=2.5)]:
            with self.assertRaises(ValidationError):
                RoomSettings(**invalid)

    def test_custom_blinds_reach_engine_and_lock_after_dealing(self):
        self.command(self.host, 'settings', settings=dict(starting_stack=4000, small_blind=25, big_blind=50, turn_seconds=60, auto_deal=False))
        self.start()
        self.assertEqual(self.room.hand.pot, 75)
        self.assertEqual(self.room.hand.betting.call_amount, 25)
        self.assertEqual(self.room.hand.betting.min_raise_to, 100)
        self.assertEqual(self.room.hand.last_full_raise, 50)
        with self.assertRaises(ValueError):
            self.command(self.host, 'settings', settings=RoomSettings())
        self.assertEqual(sum(p.stack for p in self.room.hand.players) + self.room.hand.pot, 2000)

    def test_restart_during_quiet_phase_keeps_all_remaining_time(self):
        self.start()
        self.room.deadline_at = (time.time() + 35) * 1000
        self.store.repository.save(self.room.to_record(), 'test_quiet_phase')
        self.restart()
        remaining = self.room.deadline - time.monotonic()
        self.assertGreater(remaining, 34)
        self.assertLessEqual(remaining, 35)

    def test_restart_preserves_hand_deck_tokens_and_secrets(self):
        self.start()
        before = self.room.to_record()
        deadline = self.room.deadline_at
        self.restart()
        self.assertEqual(self.room.to_record(), before)
        self.assertEqual(self.room.deadline_at, deadline)
        self.assertTrue(all(not m.sockets for m in self.room.members))
        view = self.room.snapshot(self.host)
        self.assertEqual(view['hand']['players'][1]['cards'], [])
        serialized = json.dumps(view)
        self.assertNotIn(self.guest.token, serialized)
        self.assertNotIn('_deck', serialized)
        self.assertNotIn('commands', serialized)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_continue_after_restart_uses_original_deck_and_conserves_chips(self):
        self.start()
        expected = self.room.hand.model_copy(deep=True)
        engine = self.room.engine
        while not expected.result:
            action = ActionType.CHECK if ActionType.CHECK in expected.betting.legal_actions else ActionType.CALL
            expected = engine.apply_action(expected, expected.current_player_id, action)
            while not expected.current_player_id and not expected.result:
                expected = engine.advance(expected)
        self.restart()
        while not self.room.hand.result:
            hand = self.room.hand
            actor = next(m for m in self.room.members if m.player_id == hand.current_player_id)
            chosen = 'check' if ActionType.CHECK in hand.betting.legal_actions else 'call'
            self.command(actor, 'action', action=chosen, hand_id=hand.hand_id)
        self.assertEqual(self.room.hand.model_dump(), expected.model_dump())
        self.assertEqual(sum(p.stack for p in self.room.hand.players), 2000)
        self.assertEqual(len(self.room.hand._deck), len(expected._deck))

    def test_committed_command_is_deduplicated_after_restart(self):
        self.start()
        command = self.command(self.host, 'action', action='call', hand_id=self.room.hand.hand_id)
        before = self.room.to_record()
        self.restart()
        self.store.apply(self.room, lambda: self.room.command(self.host, command), 'action')
        self.assertEqual(self.room.to_record(), before)
        count = self.store.repository.connection.execute('SELECT count(*) FROM room_events WHERE kind="action"').fetchone()[0]
        self.assertEqual(count, 1)

    def test_completed_hand_and_payout_saved_once(self):
        self.start()
        self.command(self.host, 'action', action='fold', hand_id=self.room.hand.hand_id)
        stacks = [m.stack for m in self.room.members]
        self.command(self.host, 'ready', ready=True)
        self.restart()
        self.assertEqual([m.stack for m in self.room.members], stacks)
        rows = self.store.repository.connection.execute('SELECT payload FROM completed_hands').fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0][0])['result']['pot_awarded'], 10)
        self.assertTrue(self.room.hand.result)

    def test_write_failure_rolls_back_state_command_cache_and_journal(self):
        self.start()
        before = self.room.to_record()
        self.fail_writes()
        with self.assertRaises(RoomStorageError):
            self.command(self.host, 'action', action='call', hand_id=self.room.hand.hand_id)
        self.assertEqual(self.room.to_record(), before)
        self.assertIs(self.room.members[0], self.host)
        self.assertEqual(self.store.repository.load()[0], before)
        self.assertEqual(self.store.repository.connection.execute('SELECT count(*) FROM room_events WHERE kind="action"').fetchone()[0], 0)

    def test_failed_join_and_create_do_not_leave_ghost_seats_or_rooms(self):
        before = self.room.to_record()
        self.fail_writes()
        with self.assertRaises(RoomStorageError):
            self.store.apply(self.room, lambda: self.room.join('Ghost'), 'join')
        self.assertEqual(self.room.to_record(), before)
        with self.assertRaises(RoomStorageError):
            self.store.create('Ghost room')
        self.assertEqual(len(self.store.rooms), 1)

    def test_expired_persisted_deadline_times_out_without_restarting_clock(self):
        self.start()
        self.room.deadline_at = (time.time() - 1) * 1000
        self.store.repository.save(self.room.to_record(), 'test_expiry')
        self.restart()
        self.assertLessEqual(self.room.deadline, time.monotonic())
        self.assertTrue(self.store.apply(self.room, self.room.tick, 'timeout'))
        self.assertTrue(self.host.sitting_out)
        self.assertTrue(self.room.hand.result)
        self.restart()
        self.assertTrue(self.host.sitting_out)
        self.assertIsNone(self.room.deadline)

    def test_leave_and_host_migration_survive_restart(self):
        self.command(self.host, 'leave')
        token, code = self.host.token, self.room.code
        self.store.close()
        self.store = RoomStore(self.path); self.store.open()
        self.room = self.store.get(code)
        with self.assertRaises(ValueError):
            self.room.authenticate(token)
        self.assertEqual(self.room.host_id, self.guest.player_id)

    def test_stale_command_persists_timeout_before_rejecting_action(self):
        self.start()
        self.room.deadline = time.monotonic() - 1
        command = RoomCommand(command_id='late', revision=self.room.revision, kind='action', action='call', hand_id=self.room.hand.hand_id)
        with self.assertRaises(ValueError):
            self.store.apply(self.room, lambda: self.room.command(self.host, command), 'action')
        self.restart()
        self.assertTrue(self.room.hand.result)
        self.assertTrue(self.host.sitting_out)
        self.assertNotIn('late', self.host.commands)

    def test_concurrent_commands_with_same_revision_commit_only_once(self):
        self.start()
        revision = self.room.revision

        async def submit(action):
            command = RoomCommand(command_id=action, revision=revision, kind='action',
                                  action=action, hand_id=self.room.hand.hand_id)
            async with self.room.lock:
                await asyncio.sleep(0)
                try:
                    self.store.apply(self.room, lambda: self.room.command(self.host, command), 'action')
                    return True
                except ValueError:
                    return False

        async def race():
            return await asyncio.gather(submit('call'), submit('fold'))

        self.assertEqual(sum(asyncio.get_event_loop().run_until_complete(race())), 1)
        self.restart()
        self.assertEqual(self.room.hand.pot, 20)
        self.assertEqual(self.room.revision, revision + 1)


if __name__ == '__main__':
    unittest.main()
