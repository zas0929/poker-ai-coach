import copy
import unittest
from app.models.poker import ActionType,PlayerStatus,Street
from app.services.poker_engine import PokerEngine
from app.services.solver_snapshot import prepare_solver_snapshot,UnsupportedSolverState
from research.custom_river import RiverGame,demo_ranges
from research.river_snapshot import build_river_from_snapshot,digest
from research.sidepot_reference import compare_every_path

BOARD=['2c','4d','7h','9s','Jc']


def river_state(n,fold_flop=False):
    engine=PokerEngine();state=engine.start_hand(player_count=n)
    folded=False
    while state.street!=Street.RIVER:
        if state.current_player_id is None:engine.advance(state)
        elif fold_flop and not folded and state.street==Street.FLOP:
            engine.apply_action(state,state.current_player_id,ActionType.FOLD);folded=True
        else:engine.apply_action(state,state.current_player_id,ActionType.CALL if state.betting.call_amount else ActionType.CHECK)
    return engine,state


def selection(snapshot):
    # Explicit fixture subset selected from PUBLIC ranges, never actual holdings.
    used=set(snapshot['board']);chosen={}
    for p in snapshot['players']:
        if p['status']=='folded':continue
        text=next(c['cards'] for c in p['range'] if not used.intersection((c['cards'][:2],c['cards'][2:])))
        chosen[p['id']]=[text];used.update((text[:2],text[2:]))
    return chosen


class FoldedRiverTests(unittest.TestCase):
    def test_dead_money_never_wins_and_no_folded_cards_are_invented(self):
        game=RiverGame(BOARD,[[],[('KhKd',1)],[('QhQd',1)]],pot=150,
                       stacks=(900,30,100),initial_contributions=(30,60,60),folded=(0,),
                       dealer=0,bet_sizes=(40,),raise_sizes=(80,),max_raises=1,min_bet=10)
        self.assertEqual(game.root.actor,1)
        self.assertEqual(game.deals[0][0][0],None)
        self.assertEqual(game.deals[0][2][0],None)
        self.assertTrue(all(key[0]!=0 for key in game.keys))
        for node in game.nodes:
            if node.actor!=-1:continue
            self.assertNotIn(0,node.alive)
            awards,refunds,pots=game.settle(node,game.deals[0][2])
            self.assertEqual(awards[0],0)
            self.assertEqual(game.utilities[(id(node),0)][0],-30)
            self.assertTrue(all(0 not in pot['eligible'] for pot in pots))
        compare_every_path(game)
        measured=game.measure(game.train(20,method='cfr_plus'))
        self.assertEqual(measured['unilateral_gains'][0],0)
        self.assertAlmostEqual(sum(measured['policy_payoffs']),0)

    def test_all_paths_with_folded_button_and_dead_sidepot_contributors(self):
        for n in range(3,7):
            for folded in ((0,),tuple(range(n-2))):
                ranges=[[] if p in folded else r[:1] for p,r in enumerate(demo_ranges(n))]
                prior=[30 if p in folded else 60 for p in range(n)]
                stacks=[500 if p in folded else (30 if p%2 else 100) for p in range(n)]
                game=RiverGame(BOARD,ranges,pot=sum(prior),stacks=stacks,initial_contributions=prior,
                               folded=folded,dealer=0,bet_sizes=(30,),raise_sizes=(60,),max_raises=1,min_bet=10)
                self.assertGreater(compare_every_path(game)['terminal_deal_checks'],0)

    def test_invalid_folded_slots(self):
        with self.assertRaises(ValueError):
            RiverGame(BOARD,[[],*demo_ranges(2)],folded=(0,),stacks=(5,100,100),
                      bet_sizes=(5,),min_bet=10)
        for folded,ranges in [((True,),demo_ranges(3)),((3,),demo_ranges(3)),
                              ((0,0),[[],*demo_ranges(2)]),((0,1),[[],[],demo_ranges(1)[0]]),
                              ((0,),demo_ranges(3))]:
            with self.assertRaises(ValueError):RiverGame(BOARD,ranges,folded=folded)


class RiverSnapshotAdapterTests(unittest.TestCase):
    def test_real_start_of_river_for_every_table_size(self):
        for n in range(2,7):
            _,state=river_state(n);snapshot=prepare_solver_snapshot(state)
            game,meta=build_river_from_snapshot(snapshot,selection(snapshot),bet_sizes=(10,))
            self.assertEqual(meta['seat_ids'],[p.id for p in state.players])
            self.assertEqual(meta['actor_id'],state.current_player_id)
            self.assertEqual(game.stacks,tuple(p.stack for p in state.players))
            self.assertEqual(game.initial_contributions,tuple(state.contributions[p.id] for p in state.players))
            self.assertEqual(meta['range_selection'],'explicit_subset')
            self.assertEqual(meta['range_counts'][0]['public'],1081)
            self.assertEqual(len(game.deals),1)
            self.assertFalse(meta['folded_card_bunching_modelled'])
            compare_every_path(game)

    def test_folded_real_seat_is_preserved_without_a_range(self):
        _,state=river_state(4,fold_flop=True);snapshot=prepare_solver_snapshot(state)
        game,meta=build_river_from_snapshot(snapshot,selection(snapshot),bet_sizes=(10,))
        index=next(i for i,p in enumerate(state.players) if p.status==PlayerStatus.FOLDED)
        self.assertEqual(game.folded,(index,))
        self.assertEqual(game.ranges[index],[])
        self.assertGreater(game.initial_contributions[index],0)
        self.assertEqual(len(meta['seat_ids']),4)
        compare_every_path(game)

    def test_real_prior_allin_and_sidepot_snapshot(self):
        engine=PokerEngine();state=engine.start_hand(player_count=3,starting_stacks=[30,100,200])
        engine.apply_action(state,'hero',ActionType.RAISE,30)
        engine.apply_action(state,'villain',ActionType.RAISE,60)
        engine.apply_action(state,'villain_2',ActionType.CALL)
        while state.street!=Street.RIVER:
            if state.current_player_id is None:engine.advance(state)
            else:engine.apply_action(state,state.current_player_id,ActionType.CHECK)
        snapshot=prepare_solver_snapshot(state)
        game,meta=build_river_from_snapshot(snapshot,selection(snapshot),bet_sizes=(10,))
        self.assertEqual(game.stacks,(0,40,140))
        self.assertEqual(game.initial_contributions,(30,60,60))
        self.assertEqual(game.root.actor,1)
        compare_every_path(game)

    def test_private_cards_names_notes_and_deck_cannot_change_adapter_input(self):
        _,state=river_state(3);snapshot=prepare_solver_snapshot(state);chosen=selection(snapshot)
        game,meta=build_river_from_snapshot(snapshot,chosen,bet_sizes=(10,))
        for p in state.players:p.cards=[];p.name='private'
        state._deck.reverse();state.notes.append('secret')
        other=prepare_solver_snapshot(state)
        game2,meta2=build_river_from_snapshot(other,chosen,bet_sizes=(10,))
        self.assertEqual(meta,meta2)
        self.assertEqual(game.deals,game2.deals)
        self.assertEqual(game.train(3,method='cfr_plus'),game2.train(3,method='cfr_plus'))

    def test_no_automatic_range_truncation_and_weights_are_preserved(self):
        _,state=river_state(2);snapshot=prepare_solver_snapshot(state)
        with self.assertRaisesRegex(UnsupportedSolverState,'64 raw joint'):
            build_river_from_snapshot(snapshot,bet_sizes=(10,))
        chosen=selection(snapshot)
        game,meta=build_river_from_snapshot(snapshot,chosen,bet_sizes=(10,))
        for i,p in enumerate(snapshot['players']):
            expected=next(c['weight'] for c in p['range'] if c['cards']==chosen[p['id']][0])
            self.assertEqual(game.ranges[i][0][1],expected)
        _,different=build_river_from_snapshot(snapshot,chosen,bet_sizes=(20,))
        self.assertNotEqual(meta['task_key'],different['task_key'])
        self.assertEqual(meta['source_information_key'],different['source_information_key'])

    def test_reject_other_streets_midriver_actor_and_corrupted_inputs(self):
        engine,state=river_state(3);snapshot=prepare_solver_snapshot(state);chosen=selection(snapshot)
        engine.apply_action(state,state.current_player_id,ActionType.CHECK)
        with self.assertRaisesRegex(UnsupportedSolverState,'Mid-river history'):
            build_river_from_snapshot(prepare_solver_snapshot(state),chosen,bet_sizes=(10,))
        engine.apply_action(state,state.current_player_id,ActionType.BET,10)
        with self.assertRaisesRegex(UnsupportedSolverState,'Mid-river commitments'):
            build_river_from_snapshot(prepare_solver_snapshot(state),chosen,bet_sizes=(10,))
        cases=[]
        for key,value in [('street','turn'),('actor_id','missing'),('postflop_order',[]),('schema_version',2)]:
            bad=copy.deepcopy(snapshot);bad[key]=value;bad['information_key']=digest({k:v for k,v in bad.items() if k!='information_key'});cases.append(bad)
        corrupt=copy.deepcopy(snapshot);corrupt['pot']+=1;cases.append(corrupt)
        for bad in cases:
            with self.assertRaises(UnsupportedSolverState):build_river_from_snapshot(bad,chosen,bet_sizes=(10,))
        for bad_selection in ({},{**chosen,'missing':['AhAd']},{**chosen,next(iter(chosen)):['2x3x']}):
            with self.assertRaises(UnsupportedSolverState):build_river_from_snapshot(snapshot,bad_selection,bet_sizes=(10,))
