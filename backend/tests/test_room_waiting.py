import asyncio
import unittest
from unittest.mock import patch
from fastapi import Response
from app.api import rooms
from app.models.poker import ActionType
from app.services.room_service import Room, RoomCommand, RoomSettings, RoomStore


class WaitingSeatTests(unittest.TestCase):
    def room(self, count=2, auto=False):
        room,host=RoomStore().create('Host',settings=RoomSettings(auto_deal=auto,visibility='public'))
        for i in range(count-1):room.join(f'Friend {i}')
        for m in room.members:m.ready=True;m.sockets.add(object())
        room._deal();room._settle()
        return room,host

    def command(self,room,member,kind,**kwargs):
        room.command(member,RoomCommand(command_id=f'{kind}-{room.revision}',revision=room.revision,kind=kind,**kwargs))

    def test_join_reserves_seat_without_changing_hand_or_exposing_cards(self):
        room,host=self.room()
        before=room.hand.model_dump_json();deadline=room.deadline_at
        guest=room.join('New friend',500)
        self.assertEqual(room.hand.model_dump_json(),before)
        self.assertEqual(room.deadline_at,deadline)
        view=room.snapshot(guest)
        self.assertEqual(len(view['members']),3)
        member=next(m for m in view['members'] if m['player_id']==guest.player_id)
        self.assertTrue(member['waiting_for_hand']);self.assertEqual(member['stack'],500)
        self.assertEqual(member['name'],'New friend')
        self.assertEqual(len(view['hand']['players']),2)
        self.assertTrue(all(not p['cards'] for p in view['hand']['players']))
        with self.assertRaisesRegex(ValueError,'next hand'):
            self.command(room,guest,'action',hand_id=room.hand.hand_id,action=ActionType.CALL)
        self.assertEqual(room.hand.model_dump_json(),before)

    def test_waiting_player_gets_cards_only_in_next_hand_and_keeps_buyin(self):
        room,host=self.room();guest=room.join('New friend',500);guest.sockets.add(object())
        actor=next(m for m in room.members if m.player_id==room.hand.current_player_id)
        self.command(room,actor,'action',hand_id=room.hand.hand_id,action=ActionType.FOLD)
        self.assertEqual(guest.stack,500)
        self.assertNotIn(guest.player_id,[r.player_id for r in room.hand.result.player_results])
        old=room.hand.hand_id
        for m in room.members:self.command(room,m,'ready',ready=True)
        self.command(room,host,'start')
        self.assertNotEqual(old,room.hand.hand_id)
        self.assertEqual(len(room.hand.players),3)
        view=room.snapshot(guest)
        self.assertFalse(next(m for m in view['members'] if m['player_id']==guest.player_id)['waiting_for_hand'])
        self.assertEqual(len(next(p for p in view['hand']['players'] if p['id']==guest.player_id)['cards']),2)
        self.assertEqual(room.hand.pot+sum(p.stack for p in room.hand.players),1300)

    def test_waiting_seat_survives_restore_and_auto_deals_next_hand(self):
        room,host=self.room(auto=True);guest=room.join('New friend',600)
        restored=Room(room.code);restored.restore(room.to_record())
        member=restored.authenticate(guest.token)
        self.assertTrue(restored.waiting_for_hand(member));self.assertEqual(member.stack,600)
        self.assertTrue(member.ready)
        for m in restored.members:m.sockets.add(object())
        actor=next(m for m in restored.members if m.player_id==restored.hand.current_player_id)
        self.command(restored,actor,'action',hand_id=restored.hand.hand_id,action=ActionType.FOLD)
        restored.tick()
        self.assertIsNotNone(restored.next_hand_at)
        with patch('app.services.room_service.time.time',return_value=restored.next_hand_at/1000+1):restored.tick()
        self.assertIn(member.player_id,[p.id for p in restored.hand.players])
        self.assertFalse(restored.waiting_for_hand(member))

    def test_departing_current_hand_seat_cannot_be_reused_until_settlement(self):
        room,host=self.room(6)
        departing=room.members[-1]
        self.command(room,departing,'leave')
        self.assertEqual(len(room.seated),5)
        with self.assertRaisesRegex(ValueError,'full'):room.join('Replacement')
        while not room.hand.result:
            actor=next(m for m in room.members if m.player_id==room.hand.current_player_id)
            self.command(room,actor,'action',hand_id=room.hand.hand_id,action=ActionType.FOLD)
        replacement=room.join('Replacement')
        self.assertEqual(replacement.seat,departing.seat)
        self.assertNotEqual(replacement.player_id,departing.player_id)

    def test_public_active_table_remains_joinable_until_capacity(self):
        store=RoomStore();room,host=self.room();store.rooms[room.code]=room
        def listing():
            with patch.object(rooms,'store',store):
                return asyncio.get_event_loop().run_until_complete(rooms.public_rooms(Response()))['rooms'][0]
        item=listing();self.assertTrue(item['hand_in_progress']);self.assertTrue(item['can_join']);self.assertEqual(item['seats_available'],4)
        for i in range(4):room.join(f'Waiting {i}')
        item=listing();self.assertFalse(item['can_join']);self.assertEqual(item['seats_available'],0)
        self.assertNotIn(host.token,str(item));self.assertNotIn('cards',item)
