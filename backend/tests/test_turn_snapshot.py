import copy
import random
import unittest
from unittest.mock import patch
from app.models.poker import ActionType
from app.services.poker_engine import PokerEngine
from app.services.solver_snapshot import card_text, prepare_solver_snapshot, UnsupportedSolverState
from app.services.trainer_solver import public_copy
from research.river_snapshot import combo_key, digest
from research.turn_snapshot import build_turn_from_snapshot
from research.turn_oracle import compare_every_path


def turn(n):
    engine=PokerEngine()
    with patch('app.services.poker_engine.secrets.SystemRandom',return_value=random.Random(102+n)):
        state=engine.start_hand(player_count=n)
    for _ in range(100):
        if state.street.value=='turn' and state.current_player_id=='hero': return state
        if state.current_player_id is None:engine.advance(state)
        else:engine.apply_action(state,state.current_player_id,ActionType.CHECK if ActionType.CHECK in state.betting.legal_actions else ActionType.CALL)
    raise AssertionError('No passive turn.')


def select(snapshot,hand):
    # A single-combo control per seat tests reconstruction, not range quality.
    result={'hero':[hand]};used=set(combo_key(hand))
    for p in snapshot['players']:
        if p['id']=='hero' or p['status']=='folded':continue
        text=next(r['cards'] for r in p['range'] if not set(combo_key(r['cards']))&used)
        result[p['id']]=[text];used.update(combo_key(text))
    return result


def refresh(snapshot):
    snapshot['information_key']=digest({k:v for k,v in snapshot.items() if k!='information_key'})
    return snapshot


class TurnSnapshotTests(unittest.TestCase):
    def test_actual_turn_decisions_one_to_five_opponents_match_the_game(self):
        for n in range(2,7):
            state=turn(n);snapshot=prepare_solver_snapshot(public_copy(state))
            hand=''.join(card_text(c) for p in state.players if p.id=='hero' for c in p.cards)
            chosen=select(snapshot,hand)
            game,meta=build_turn_from_snapshot(snapshot,chosen,turn_bet_sizes=(10,),river_bet_sizes=(10,))
            self.assertEqual(meta['actor_id'],'hero')
            self.assertEqual(meta['decision_pot'],state.pot)
            self.assertEqual(meta['seat_ids'][game.root.actor],'hero')
            self.assertEqual(game.root_state.invested,tuple(p.current_bet for p in state.players))
            compare_every_path(game,(0,len(game.outcomes)-1))

    def test_poisoned_hidden_cards_and_actual_future_river_do_not_change_input(self):
        state=turn(3);poison=state.model_copy(deep=True)
        for p in poison.players:
            if p.id!='hero':p.cards=poison.players[0].cards
        poison._deck.reverse()
        self.assertEqual(prepare_solver_snapshot(public_copy(state)),prepare_solver_snapshot(public_copy(poison)))

    def test_observed_bet_and_raise_are_reconstructed_from_chips_added(self):
        state=turn(2);engine=PokerEngine()
        engine.apply_action(state,'hero',ActionType.BET,10)
        engine.apply_action(state,state.current_player_id,ActionType.RAISE,30)
        snap=prepare_solver_snapshot(public_copy(state))
        hand=''.join(card_text(c) for p in state.players if p.id=='hero' for c in p.cards)
        game,meta=build_turn_from_snapshot(snap,select(snap,hand),turn_bet_sizes=(10,),turn_raise_sizes=(50,),turn_max_raises=1,river_bet_sizes=())
        self.assertEqual(meta['observed_raises'],1)
        self.assertEqual(meta['last_full_raise'],20)
        self.assertIn('RAISE 50',game.root.actions)
        compare_every_path(game)

    def test_public_boundary_future_actions_and_tree_override_are_rejected(self):
        state=turn(2);snapshot=prepare_solver_snapshot(public_copy(state))
        hand=''.join(card_text(c) for p in state.players if p.id=='hero' for c in p.cards)
        selected=select(snapshot,hand)
        mutations=(lambda s:s.update(deck=['As']),lambda s:s['players'][1].update(cards=['As','Ks']),
                   lambda s:s.update(pot=s['pot']+1),lambda s:s.update(actor_id='villain'),
                   lambda s:s['history'].append({'player_id':'hero','action':'check','amount_added':None,'street':'river'}),
                   lambda s:s.update(postflop_order=list(reversed(s['postflop_order']))))
        for mutate in mutations:
            bad=copy.deepcopy(snapshot);mutate(bad);refresh(bad)
            with self.assertRaises(UnsupportedSolverState):build_turn_from_snapshot(bad,selected)
        with self.assertRaises(UnsupportedSolverState):build_turn_from_snapshot(snapshot,selected,board=['As']*4)
        with self.assertRaises(UnsupportedSolverState):build_turn_from_snapshot(snapshot,selected,max_outcomes=1)
        bad=copy.deepcopy(snapshot);bad['pot']+=1
        with self.assertRaises(UnsupportedSolverState):build_turn_from_snapshot(bad,selected)

    def test_selection_must_be_explicit_legal_and_complete(self):
        state=turn(2);snapshot=prepare_solver_snapshot(public_copy(state))
        hand=''.join(card_text(c) for p in state.players if p.id=='hero' for c in p.cards)
        selected=select(snapshot,hand)
        for bad in ({'hero':[hand]}, {**selected,'hero':['AsAs']}, {**selected,'hero':[hand,hand]}):
            with self.assertRaises(UnsupportedSolverState):build_turn_from_snapshot(snapshot,bad)
