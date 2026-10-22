import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.services.room_service import RoomSettings, RoomCommand, RoomStore
from app.services.room_repository import RoomStorageError


class AutoDealTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'rooms.sqlite3'
        self.store = RoomStore(self.path); self.store.open()
        self.room, self.host = self.store.create('Host')
        self.guest = self.store.apply(self.room, lambda: self.room.join('Guest'), 'join')
        for member in self.room.members: member.sockets.add(object())
        self.counter = 0

    def tearDown(self):
        self.store.close(); self.temp.cleanup()

    def tick(self, second):
        with patch('app.services.room_service.time.time', return_value=second):
            return self.store.apply(self.room, self.room.tick, 'timer')

    def command(self, member, kind, **values):
        self.counter += 1
        command = RoomCommand(command_id=str(self.counter), revision=self.room.revision, kind=kind, **values)
        self.store.apply(self.room, lambda: self.room.command(member, command), kind, command.command_id, member.player_id)

    def test_new_table_defaults(self):
        settings = RoomSettings()
        self.assertEqual((settings.starting_stack, settings.small_blind, settings.big_blind), (400, 1, 2))
        self.assertTrue(settings.auto_deal)
        self.assertTrue(all(member.ready for member in self.room.members))

    def test_first_and_next_hand_deal_without_host_commands(self):
        self.assertTrue(self.tick(1000)); self.assertIsNone(self.room.hand)
        self.assertFalse(self.tick(1007.99)); self.assertTrue(self.tick(1008))
        first = self.room.hand.hand_id
        self.assertEqual(sum(p.stack for p in self.room.hand.players) + self.room.hand.pot, 800)
        self.command(self.host, 'action', hand_id=first, action='fold')
        self.assertTrue(self.room.hand.result)
        self.assertTrue(all(member.ready for member in self.room.members))
        self.tick(2000); self.tick(2008)
        self.assertNotEqual(self.room.hand.hand_id, first)
        self.assertEqual(sum(p.stack for p in self.room.hand.players) + self.room.hand.pot, 800)

    def test_unready_cancels_scheduled_hand_and_can_resume(self):
        self.tick(1000)
        with patch('app.services.room_service.time.time', return_value=1001):
            self.command(self.guest, 'ready', ready=False)
        self.assertTrue(self.tick(1001)); self.assertIsNone(self.room.next_hand_at)
        self.assertFalse(self.tick(1010)); self.assertIsNone(self.room.hand)
        self.command(self.guest, 'ready', ready=True)
        self.tick(2000); self.tick(2008)
        self.assertIsNotNone(self.room.hand)

    def test_disconnected_player_prevents_deal(self):
        self.tick(1000)
        self.guest.sockets.clear()
        self.tick(1008)
        self.assertIsNone(self.room.hand)
        self.assertIsNone(self.room.next_hand_at)

    def test_manual_mode_never_schedules(self):
        self.command(self.host, 'settings', settings=RoomSettings(auto_deal=False))
        self.assertFalse(self.tick(1000))
        self.assertIsNone(self.room.next_hand_at)
        self.assertTrue(all(not member.ready for member in self.room.members))

    def test_schedule_survives_restart_but_waits_for_connections(self):
        self.tick(1000)
        code = self.room.code
        self.store.close(); self.store.open(); self.room = self.store.get(code)
        self.assertEqual(self.room.next_hand_at, 1008000)
        self.tick(1010)
        self.assertIsNone(self.room.hand)
        for member in self.room.members: member.sockets.add(object())
        self.tick(2000); self.tick(2008)
        self.assertIsNotNone(self.room.hand)

    def test_schedule_write_failure_restores_timer_and_readiness(self):
        self.store.repository.connection.execute("CREATE TRIGGER fail_schedule BEFORE INSERT ON room_events BEGIN SELECT RAISE(ABORT,'test failure'); END")
        self.store.repository.connection.commit()
        with self.assertRaises(RoomStorageError): self.tick(1000)
        self.assertIsNone(self.room.next_hand_at)
        self.assertTrue(all(member.ready for member in self.room.members))
