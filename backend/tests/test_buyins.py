import tempfile
import unittest
from pathlib import Path
from app.services.room_service import RoomCommand, RoomStore, RoomSettings
from app.services.room_repository import RoomStorageError


class BuyInTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = RoomStore(Path(self.temp.name) / 'room.sqlite3'); self.store.open()
        self.room, self.host = self.store.create('Host', 600, RoomSettings(auto_deal=False))
        self.guest = self.store.apply(self.room, lambda: self.room.join('Guest', 200), 'join')
        for member in self.room.members: member.sockets.add(object())
        self.counter = 0

    def tearDown(self):
        self.store.close(); self.temp.cleanup()

    def command(self, member, kind, **values):
        self.counter += 1
        command = RoomCommand(command_id=str(self.counter), revision=self.room.revision, kind=kind, **values)
        self.store.apply(self.room, lambda: self.room.command(member, command), kind, command.command_id, member.player_id)
        return command

    def approve(self, member):
        request = next(r for r in self.room.top_up_requests if r['player_id'] == member.player_id and r['status'] == 'pending')
        return self.command(self.host, 'approve_top_up', request_id=request['request_id'])

    def start(self):
        for member in self.room.members: self.command(member, 'ready', ready=True)
        self.command(self.host, 'start')

    def test_custom_stacks_reach_engine_without_extra_chips(self):
        self.start()
        self.assertEqual(sum(p.stack for p in self.room.hand.players) + self.room.hand.pot, 800)

    def test_top_up_retries_credit_only_once_and_survive_restart(self):
        command = self.command(self.guest, 'top_up', amount=50)
        self.store.apply(self.room, lambda: self.room.command(self.guest, command), 'top_up')
        self.assertEqual(self.guest.stack, 200)
        approval = self.approve(self.guest)
        self.store.apply(self.room, lambda: self.room.command(self.host, approval), 'approve_top_up')
        self.assertEqual(self.guest.stack, 250)
        code, token = self.room.code, self.guest.token
        self.store.close(); self.store.open()
        self.assertEqual(self.store.get(code).authenticate(token).stack, 250)

    def test_top_up_during_hand_and_invalid_amounts_do_not_move_chips(self):
        for amount in [0, -1, 1000001]:
            with self.assertRaises(ValueError): self.command(self.host, 'top_up', amount=amount)
        self.assertEqual(self.host.stack, 600)
        self.start()
        with self.assertRaises(ValueError): self.command(self.host, 'top_up', amount=50)
        self.assertEqual(sum(p.stack for p in self.room.hand.players) + self.room.hand.pot, 800)

    def test_failed_top_up_is_rolled_back(self):
        self.store.repository.connection.execute("CREATE TRIGGER fail_topup BEFORE INSERT ON room_events BEGIN SELECT RAISE(ABORT,'test failure'); END")
        self.store.repository.connection.commit()
        with self.assertRaises(RoomStorageError): self.command(self.host, 'top_up', amount=50)
        self.assertEqual(self.host.stack, 600)

    def test_invalid_buy_in_does_not_add_a_seat(self):
        for amount in [0, 1, True, 2.5, 1000001]:
            with self.assertRaises(ValueError): self.room.join('Invalid', amount)
        self.assertEqual(len(self.room.members), 2)

    def test_settings_preserve_individual_buy_ins(self):
        self.command(self.host, 'settings', settings=dict(starting_stack=400, small_blind=2, big_blind=4, turn_seconds=30))
        self.assertEqual([m.stack for m in self.room.members], [600, 200])

    def test_top_up_after_completed_hand_is_not_overwritten_by_old_payout(self):
        self.start()
        self.command(self.host, 'action', hand_id=self.room.hand.hand_id, action='fold')
        before = self.host.stack
        self.command(self.host, 'top_up', amount=100)
        self.approve(self.host)
        self.assertEqual(self.host.stack, before + 100)
        self.command(self.guest, 'ready', ready=True)
        self.assertEqual(self.host.stack, before + 100)

    def test_top_up_restores_auto_readiness_after_busting(self):
        self.room.settings.auto_deal = True
        self.host.stack = 0
        self.host.ready = False
        self.command(self.host, 'top_up', amount=100)
        self.approve(self.host)
        self.assertEqual(self.host.stack, 100)
        self.assertTrue(self.host.ready)

    def test_top_up_respects_sit_out_and_manual_readiness(self):
        for auto_deal, sitting_out in [(True, True), (False, False)]:
            self.room.settings.auto_deal = auto_deal
            self.host.stack = 0
            self.host.ready = False
            self.host.sitting_out = sitting_out
            self.command(self.host, 'top_up', amount=100)
            self.approve(self.host)
            self.assertFalse(self.host.ready)

    def test_busted_player_can_top_up_while_others_play(self):
        third = self.store.apply(self.room, lambda: self.room.join('Third', 400), 'join')
        third.sockets.add(object())
        self.room.settings.auto_deal = True
        self.host.stack = 0
        self.host.ready = False
        for member in (self.guest, third): self.command(member, 'ready', ready=True)
        self.command(self.host, 'start')
        before = self.room.hand.model_dump_json()
        self.command(self.host, 'top_up', amount=400)
        self.approve(self.host)
        self.assertEqual(self.host.stack, 400)
        self.assertTrue(self.host.ready)
        self.assertEqual(self.room.hand.model_dump_json(), before)

    def test_guest_cannot_review_or_duplicate_pending_request(self):
        self.command(self.guest, 'top_up', amount=50)
        request = self.room.top_up_requests[0]
        for kind in ('approve_top_up', 'decline_top_up'):
            with self.assertRaisesRegex(ValueError, 'Only the host'):
                self.command(self.guest, kind, request_id=request['request_id'])
        with self.assertRaisesRegex(ValueError, 'already have'):
            self.command(self.guest, 'top_up', amount=60)
        self.assertEqual(self.guest.stack, 200)
        self.assertEqual(len(self.room.top_up_requests), 1)

    def test_pending_request_survives_restart_and_decline_allows_retry(self):
        self.command(self.guest, 'top_up', amount=50)
        record = self.room.to_record()
        self.room.restore(record)
        request = self.room.snapshot(self.host)['top_up_requests'][0]
        self.command(self.host, 'decline_top_up', request_id=request['request_id'])
        self.assertEqual(self.guest.stack, 200)
        self.assertEqual(self.room.snapshot(self.guest)['top_up_requests'][0]['status'], 'declined')
        with self.assertRaisesRegex(ValueError, 'already been reviewed'):
            self.command(self.host, 'approve_top_up', request_id=request['request_id'])
        self.command(self.guest, 'top_up', amount=70)
        self.approve(self.guest)
        self.assertEqual(self.guest.stack, 270)

    def test_pending_requests_pause_dealing_and_restart_full_countdown(self):
        self.room.settings.auto_deal = True
        for member in self.room.members: self.command(member, 'ready', ready=True)
        self.room.tick()
        self.assertIsNotNone(self.room.next_hand_at)
        self.command(self.guest, 'top_up', amount=100)
        self.assertIsNone(self.room.next_hand_at)
        self.assertFalse(self.room.tick())
        with self.assertRaisesRegex(ValueError, 'Review pending'):
            self.command(self.host, 'start')
        self.approve(self.guest)
        self.room.tick()
        self.assertIsNotNone(self.room.next_hand_at)
        self.assertEqual(self.guest.stack, 300)

    def test_failed_approval_rolls_back_credit_and_request_status(self):
        self.command(self.guest, 'top_up', amount=50)
        self.store.repository.connection.execute("CREATE TRIGGER fail_approval BEFORE INSERT ON room_events BEGIN SELECT RAISE(ABORT,'test failure'); END")
        self.store.repository.connection.commit()
        with self.assertRaises(RoomStorageError): self.approve(self.guest)
        self.assertEqual(self.guest.stack, 200)
        self.assertEqual(self.room.top_up_requests[0]['status'], 'pending')
        self.store.repository.connection.execute('DROP TRIGGER fail_approval')
        self.store.repository.connection.commit()
        self.approve(self.guest)
        self.assertEqual(self.guest.stack, 250)
        with self.assertRaisesRegex(ValueError, 'already been reviewed'):
            self.command(self.host, 'approve_top_up', request_id=self.room.top_up_requests[0]['request_id'])
        self.assertEqual(self.guest.stack, 250)

    def test_leaving_cancels_request_and_new_host_can_review_remaining_requests(self):
        third = self.room.join('Third', 300)
        self.command(self.guest, 'top_up', amount=50)
        self.command(third, 'top_up', amount=70)
        self.command(self.guest, 'leave')
        self.assertEqual(self.room.top_up_requests[0]['status'], 'cancelled')
        self.command(self.host, 'leave')
        self.command(third, 'approve_top_up', request_id=self.room.top_up_requests[1]['request_id'])
        self.assertEqual(third.stack, 370)

    def test_approval_revalidates_stack_cap(self):
        self.command(self.guest, 'top_up', amount=999800)
        self.guest.stack = 201
        with self.assertRaisesRegex(ValueError, '1000000'):
            self.approve(self.guest)
        self.assertEqual(self.room.top_up_requests[0]['status'], 'pending')
        self.assertEqual(self.guest.stack, 201)
