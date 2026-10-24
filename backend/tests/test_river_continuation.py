"""Public river replay, reopening rights and independent engine continuation checks."""
import copy
import unittest
from app.models.poker import ActionType, Street
from app.services.solver_snapshot import prepare_solver_snapshot, UnsupportedSolverState
from research.river_replay import replay_river
from research.river_snapshot import build_river_from_snapshot, digest
from research.sidepot_reference import compare_every_path
from test_river_snapshot import river_state, selection


class RiverContinuationTests(unittest.TestCase):
    def build(self,state):
        snapshot=prepare_solver_snapshot(state)
        sizes=dict(bet_sizes=(10,),raise_sizes=(80,),max_raises=1) if len(state.players)>=5 else dict(bet_sizes=(10,40),raise_sizes=(80,120),max_raises=2)
        game,meta=build_river_from_snapshot(snapshot,selection(snapshot),**sizes)
        ids=[p.id for p in state.players]
        self.assertEqual(ids[game.root.actor],state.current_player_id)
        self.assertEqual(game.root_state.invested,tuple(p.current_bet for p in state.players))
        self.assertEqual(game.root_state.increment,state.last_full_raise)
        self.assertEqual({ids[i]:v for i,v in enumerate(game.root_state.acted) if v is not None},state.acted_at_bet)
        self.assertEqual(game.decision_pot,state.pot)
        self.assertEqual(game.pot,sum(state.contributions[p.id]-p.current_bet for p in state.players))
        compare_every_path(game)
        return game,meta

    def act(self,engine,state,action,amount=None):
        engine.apply_action(state,state.current_player_id,ActionType(action),amount)

    def test_checks_bets_calls_raises_and_folds_two_to_six(self):
        for n in range(2,7):
            with self.subTest(players=n):
                engine,state=river_state(n)
                for action,amount in [('check',None),('bet',10),('raise',40),('call',None)]:
                    if state.current_player_id is None:break
                    self.act(engine,state,action,amount)
                    if state.current_player_id:self.build(state)
                if n>=4 and state.current_player_id:
                    self.act(engine,state,'fold')
                    if state.current_player_id:
                        game,_=self.build(state)
                        self.assertTrue(game.folded)
                        self.assertTrue(all(game.deals[0][0][i] is None for i in game.folded))

    def test_short_allin_does_not_reopen_but_cumulative_increases_do(self):
        engine,state=river_state(3)
        state.players[2].stack=60
        self.act(engine,state,'bet',40)
        self.act(engine,state,'raise',60)
        self.act(engine,state,'call')
        game,_=self.build(state)
        self.assertEqual(game.root.actor,1)
        self.assertEqual(game.root.actions,('FOLD','CALL'))
        engine,state=river_state(4)
        state.players[3].stack=60;state.players[0].stack=80
        for action,amount in [('check',None),('bet',40),('raise',60),('raise',80),('call',None)]:
            self.act(engine,state,action,amount)
            self.build(state)
        game,_=self.build(state)
        self.assertEqual(game.root.actor,2)
        self.assertIn('RAISE 120',game.root.actions)
        self.assertEqual(game.root_state.increment,40)
        self.assertEqual(game.root_state.raises,2)

    def test_unacted_player_may_raise_after_short_allin(self):
        engine,state=river_state(3);state.players[2].stack=60
        self.act(engine,state,'bet',40);self.act(engine,state,'raise',60)
        game,_=self.build(state)
        self.assertEqual(game.root.actor,0)
        self.assertIn('RAISE 120',game.root.actions)

    def test_prefix_fold_prior_allin_and_no_hidden_input(self):
        engine,state=river_state(4,fold_flop=True)
        self.act(engine,state,'bet',10)
        self.act(engine,state,'fold')
        game,meta=self.build(state)
        for p in state.players:p.cards=[];p.name='secret'
        state._deck.reverse();state.notes.append('secret')
        other,othermeta=self.build(state)
        self.assertEqual(meta,othermeta)
        self.assertEqual(game.train(5,method='cfr_plus'),other.train(5,method='cfr_plus'))
        # All-in from a prior street remains eligible for the main pot.
        from app.services.poker_engine import PokerEngine
        engine=PokerEngine();state=engine.start_hand(player_count=3,starting_stacks=[30,100,200])
        engine.apply_action(state,'hero',ActionType.RAISE,30)
        engine.apply_action(state,'villain',ActionType.RAISE,60)
        engine.apply_action(state,'villain_2',ActionType.CALL)
        while state.street!=Street.RIVER:
            if state.current_player_id is None:engine.advance(state)
            else:self.act(engine,state,'check')
        self.act(engine,state,'bet',10)
        self.build(state)

    def test_invalid_replay_and_public_commitments_fail_explicitly(self):
        bad=[[(0,'check',None)],[(1,'call',10)],[(1,'bet',5)],
             [(1,'check',0.0)],[(1,'bet',10),(2,'check',None)],
             [(1,'bet',10),(2,'call',9)],[(1,'raise',10)],
             [(1,'bet',40),(2,'raise',60),(0,'call',60),(1,'raise',80)]]
        for actions in bad:
            with self.subTest(actions=actions),self.assertRaises(ValueError):
                replay_river((100,100,60),0,10,(),actions)
        for actions,folded in [([(1,'fold',None)],()), ([(1,'fold',None),(1,'fold',None)],(1,)),
                               ([(1,'check',None)]*129,())]:
            with self.assertRaises(ValueError):replay_river((100,)*3,0,10,folded,actions)
        engine,state=river_state(3);self.act(engine,state,'bet',10)
        original=prepare_solver_snapshot(state)
        mutations=[lambda s:s['history'][-1].update(amount_added=11),
                   lambda s:s.update(actor_id=s['players'][0]['id']),
                   lambda s:s['history'].pop(),
                   lambda s:s['history'][-1].update(action='check'),
                   lambda s:s['players'][1].update(street_committed=9)]
        for mutate in mutations:
            snapshot=copy.deepcopy(original);mutate(snapshot)
            snapshot['information_key']=digest({k:v for k,v in snapshot.items() if k!='information_key'})
            with self.assertRaises(UnsupportedSolverState):
                build_river_from_snapshot(snapshot,selection(original),bet_sizes=(10,))
        # An already closed round cannot be reopened by the research tree.
        cursor=replay_river((100,)*2,0,10,(),[(1,'check',None),(0,'check',None)])
        self.assertEqual(cursor.pending,())
        with self.assertRaises(ValueError):
            replay_river((100,)*2,0,10,(),[(1,'check',None),(0,'check',None),(1,'bet',10)])
