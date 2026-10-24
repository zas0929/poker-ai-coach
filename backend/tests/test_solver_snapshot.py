import json
import unittest
from app.models.poker import ActionType, Card, Rank, Street, Suit
from app.services.poker_engine import PokerEngine
from app.services.range_service import RangeService
from app.services.solver_snapshot import prepare_solver_snapshot, solver_availability, UnsupportedSolverState

class SolverSnapshotTests(unittest.TestCase):
    def test_all_table_sizes_preserve_full_ranges_and_never_claim_a_multiway_solve(self):
        for count in range(2,7):
            with self.subTest(count=count):
                state=PokerEngine().start_hand(player_count=count)
                snapshot=prepare_solver_snapshot(state)
                self.assertEqual(snapshot['live_player_count'],count)
                self.assertEqual(len(snapshot['players']),count)
                for p in snapshot['players']:
                    self.assertEqual(len(p['range']),1326)
                availability=solver_availability(snapshot)
                self.assertFalse(availability['can_solve'])
                self.assertEqual(availability['local_prototype']['matches_player_count'],count==2)

    def test_hidden_cards_deck_notes_and_names_do_not_change_public_snapshot(self):
        state=PokerEngine().start_hand(player_count=6)
        expected=prepare_solver_snapshot(state)
        for p in state.players:
            p.cards=[Card(rank=Rank.ACE,suit=Suit.SPADES)]*2
            p.name='private-name'
        state._deck.reverse();state.notes.append('private-note')
        self.assertEqual(expected,prepare_solver_snapshot(state))
        text=json.dumps(expected)
        self.assertNotIn('private-name',text);self.assertNotIn('private-note',text)
        self.assertNotIn('_deck',text)

    def test_public_ranges_do_not_exclude_an_actual_hero_combo(self):
        state=PokerEngine().start_hand()
        actual={ (c.rank,c.suit) for c in state.players[0].cards }
        for player in state.players:
            inferred=RangeService().infer_public(state,player.id)
            self.assertTrue(any({(c.rank,c.suit) for c in combo.cards}==actual for combo in inferred.combos))

    def test_history_amounts_and_public_actions_change_identity(self):
        engine=PokerEngine();state=engine.start_hand()
        before=prepare_solver_snapshot(state)
        next_state=engine.apply_action(state, state.current_player_id, ActionType.RAISE,30)
        after=prepare_solver_snapshot(next_state)
        self.assertNotEqual(before['information_key'],after['information_key'])
        self.assertEqual(after['history'][-1]['amount_added'],25)
        self.assertEqual(after['pot'],sum(p['total_committed'] for p in after['players']))

    def test_reject_missing_contributions_duplicate_board_or_future_history(self):
        state=PokerEngine().start_hand()
        missing=state.model_copy(deep=True);missing.contributions={}
        future=state.model_copy(deep=True);future.history[0].street=Street.RIVER
        no_actor=state.model_copy(deep=True);no_actor.current_player_id=None
        for invalid in (missing,future,no_actor):
            with self.assertRaises(UnsupportedSolverState):prepare_solver_snapshot(invalid)

    def test_real_engine_river_snapshots_for_every_table_size(self):
        for count in range(2,7):
            engine=PokerEngine();state=engine.start_hand(player_count=count)
            while state.street!=Street.RIVER:
                if state.current_player_id is None:engine.advance(state)
                else:engine.apply_action(state,state.current_player_id,ActionType.CALL if state.betting.call_amount else ActionType.CHECK)
            snapshot=prepare_solver_snapshot(state)
            self.assertEqual(snapshot['live_player_count'],count)
            self.assertEqual(snapshot['postflop_order'][0],state.players[1].id)
            for public in snapshot['players']:
                self.assertEqual(len(public['range']),1081)
                board=set(snapshot['board'])
                self.assertTrue(all(not board.intersection((c['cards'][:2],c['cards'][2:])) for c in public['range']))
            # Equal cards/board/history produce the same public task regardless of holdings.
            key=snapshot['information_key']
            for player in state.players:player.cards=[]
            self.assertEqual(prepare_solver_snapshot(state)['information_key'],key)

    def test_folded_dead_money_and_unequal_stacks_are_preserved(self):
        engine=PokerEngine();state=engine.start_hand(player_count=6,starting_stacks=[300,200,150,100,250,400])
        folder=state.current_player_id
        engine.apply_action(state,folder,ActionType.FOLD)
        snapshot=prepare_solver_snapshot(state)
        folded=next(p for p in snapshot['players'] if p['id']==folder)
        self.assertEqual(snapshot['live_player_count'],5)
        self.assertNotIn('range',folded)
        self.assertEqual([p['stack'] for p in snapshot['players']],[p.stack for p in state.players])
        self.assertEqual(snapshot['pot'],sum(p['total_committed'] for p in snapshot['players']))
        self.assertNotIn(folder,snapshot['postflop_order'])

    def test_allin_and_sidepot_contributions_are_not_collapsed_into_one_stack(self):
        engine=PokerEngine();state=engine.start_hand(player_count=3,starting_stacks=[50,100,200])
        engine.apply_action(state,'hero',ActionType.RAISE,50)
        engine.apply_action(state,'villain',ActionType.RAISE,100)
        snapshot=prepare_solver_snapshot(state)
        self.assertEqual(snapshot['live_player_count'],3)
        self.assertEqual([p['stack'] for p in snapshot['players']],[0,0,190])
        self.assertEqual([p['total_committed'] for p in snapshot['players']],[50,100,10])
        self.assertEqual(snapshot['actor_id'],'villain_2')
