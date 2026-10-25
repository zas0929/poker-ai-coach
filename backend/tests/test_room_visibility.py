import asyncio
import unittest
from unittest.mock import patch
from fastapi import Response
from app.api import rooms
from app.services.room_service import RoomStore, RoomSettings, RoomCommand, Room
from app.models.poker import ActionType

class RoomVisibilityTests(unittest.TestCase):
    def test_listing_is_opt_in_and_exposes_no_secrets(self):
        store=RoomStore()
        private,_=store.create('Private')
        public,host=store.create('Public',settings=RoomSettings(visibility='public'))
        with patch.object(rooms,'store',store):
            response=Response(); result=asyncio.get_event_loop().run_until_complete(rooms.public_rooms(response))
        self.assertEqual([r['code'] for r in result['rooms']],[public.code])
        self.assertNotIn(host.token,str(result));self.assertNotIn('Public',str(result))
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        restored=Room(public.code);restored.restore(public.to_record())
        self.assertEqual(restored.settings.visibility,'public')

    def test_folded_cards_only_shared_after_owner_opt_in_and_reset_next_hand(self):
        store=RoomStore();room,a=store.create('A',settings=RoomSettings(auto_deal=False))
        b=room.join('B')
        for member in (a,b):member.ready=True;member.sockets.add(object())
        room._deal()
        actor=next(m for m in room.members if m.player_id==room.hand.current_player_id)
        other=next(m for m in room.members if m is not actor)
        room.engine.apply_action(room.hand,actor.player_id,ActionType.FOLD)
        self.assertTrue(next(p for p in room.snapshot(actor)['hand']['players'] if p['id']==actor.player_id)['cards'])
        self.assertFalse(next(p for p in room.snapshot(other)['hand']['players'] if p['id']==actor.player_id)['cards'])
        def command(member):
            room.command(member,RoomCommand(command_id='show-'+member.player_id,revision=room.revision,kind='show_fold',hand_id=room.hand.hand_id))
        with self.assertRaises(ValueError):command(other)
        command(actor)
        self.assertTrue(next(p for p in room.snapshot(other)['hand']['players'] if p['id']==actor.player_id)['cards'])
        restored=Room(room.code);restored.restore(room.to_record())
        self.assertEqual(restored.revealed_folds,{actor.player_id})
        for member in (a,b):member.ready=True
        room._deal();self.assertEqual(room.revealed_folds,set())

class TrainingRestartTests(unittest.TestCase):
    def test_refresh_retains_hand_but_explicit_new_game_replaces_it(self):
        from app.api import hand
        previous=hand.current_state
        binding=hand.training_owner.set(None)
        try:
            hand.current_state=None
            first=hand.start_hand(player_count=2)
            self.assertEqual(hand.start_hand(player_count=2).hand_id,first.hand_id)
            self.assertNotEqual(hand.start_hand(player_count=2,restart=True).hand_id,first.hand_id)
        finally:
            hand.current_state=previous
            hand.training_owner.reset(binding)

    def test_next_after_fold_finishes_existing_pot_and_preserves_stacks(self):
        from app.api import hand
        from backend.tests.test_turn_snapshot import turn
        state=turn(3)
        hand.engine.apply_action(state,'hero',ActionType.FOLD)
        total=state.pot+sum(p.stack for p in state.players)
        owner='ux-fold-test';binding=hand.training_owner.set(owner)
        previous=hand.profile_states.get(owner)
        hand.profile_states[owner]=(state,hand.monotonic())
        try:
            new=hand.start_hand(restart=True)
            self.assertIsNotNone(state.result)
            self.assertNotEqual(new.hand_id,state.hand_id)
            self.assertEqual(new.pot+sum(p.stack for p in new.players),total)
        finally:
            hand.training_owner.reset(binding)
            if previous is None:hand.profile_states.pop(owner,None)
            else:hand.profile_states[owner]=previous
