"""Turn prefix/raise regressions against production, including future river play."""
import unittest
from research.custom_river import demo_ranges
from research.native_cfr import load_library
from research.turn_reference import TurnGame, REVEAL
from research.turn_oracle import compare_every_path

BOARD = ('2c', '4d', '7h', '9s')


def follow(game, *actions):
    node = game.root
    for action in actions:
        node = node.children[node.actions.index(action)]
    return node


class TurnContinuationTests(unittest.TestCase):
    def game(self, n=2, **kwargs):
        config = dict(pot=20*n, initial_contributions=(20,)*n, stack=40,
                      turn_bet_sizes=(10,), turn_raise_sizes=(20,40), turn_max_raises=1,
                      river_bet_sizes=(10,), river_raise_sizes=(20,), river_max_raises=1,
                      min_bet=5)
        config.update(kwargs)
        return TurnGame(BOARD, [r[:1] for r in demo_ranges(n)], **config)

    def test_prefix_root_is_actual_actor_and_future_raise_cap_excludes_observed_raises(self):
        g=self.game(turn_actions=((0,'bet',5),(1,'raise',10)),turn_raise_sizes=(20,))
        self.assertEqual(g.root.actor,0)
        self.assertEqual(g.root.invested,(5,10))
        self.assertEqual(g.root.actions,('FOLD','CALL','RAISE 20'))
        self.assertEqual(g.decision_pot,55)
        self.assertEqual(g.root_state.raises,1)
        self.assertEqual(follow(g,'RAISE 20').actions,('FOLD','CALL'))
        self.assertEqual(follow(g,'CALL').actor,REVEAL)
        compare_every_path(g)

    def test_short_raise_does_not_reopen_and_cumulative_short_raises_do(self):
        short=self.game(3,stacks=(100,45,100),turn_bet_sizes=(40,),turn_raise_sizes=(80,),
                        turn_actions=((0,'bet',40),(1,'raise',45),(2,'call',45)))
        self.assertEqual(short.root.actor,0)
        self.assertEqual(short.root.actions,('FOLD','CALL'))
        cumulative=self.game(4,stacks=(200,60,80,200),turn_raise_sizes=(120,),
                             turn_actions=((0,'bet',40),(1,'raise',60),(2,'raise',80),(3,'call',80)),
                             river_bet_sizes=(),river_raise_sizes=(),river_max_raises=0)
        self.assertIn('RAISE 120',cumulative.root.actions)
        self.assertEqual(cumulative.root_state.increment,40)
        compare_every_path(short,(0,))
        compare_every_path(cumulative,(0,))

    def test_checked_player_can_raise_after_a_bet_and_raise_minimum_is_respected(self):
        g=self.game(turn_actions=((0,'check',None),(1,'bet',10)),turn_raise_sizes=(15,20))
        self.assertEqual(g.root.actions,('FOLD','CALL','RAISE 20'))
        self.assertEqual(g.root.history,((0,'CHECK'),(1,'BET 10')))
        # A configured total below a full raise is allowed only as the actor's all-in.
        short=self.game(stacks=(15,40),turn_actions=((0,'check',None),(1,'bet',10)),turn_raise_sizes=(15,))
        self.assertIn('RAISE 15',short.root.actions)
        compare_every_path(short)

    def test_raise_cap_resets_for_river_and_street_commitments_reset(self):
        g=self.game(stack=60,turn_max_raises=1,river_max_raises=1)
        reveal=follow(g,'BET 10','RAISE 20','CALL')
        self.assertEqual(reveal.actor,REVEAL)
        river=reveal.children[0]
        self.assertEqual(river.invested,(20,20))
        self.assertEqual(river.actions,('CHECK','BET 10'))
        reply=river.children[river.actions.index('BET 10')]
        self.assertIn('RAISE 20',reply.actions)
        self.assertEqual(reply.children[reply.actions.index('RAISE 20')].actions,('FOLD','CALL'))
        compare_every_path(g,(0,len(g.outcomes)-1))

    def test_every_continuation_path_two_to_six_seats_with_prefix_and_short_stacks(self):
        for n in range(2,7):
            # Prefix has a bet, all other seats will respond from the actual cursor.
            # One raise can put the short stacks all-in; both future streets remain.
            g=self.game(n,stacks=tuple([8,12,16,20,24,28][:n]),
                        turn_bet_sizes=(5,),turn_raise_sizes=(10,),
                        turn_actions=((0,'bet',5),),river_bet_sizes=(5,),
                        river_raise_sizes=(),river_max_raises=0)
            checked=compare_every_path(g,(0,len(g.outcomes)-1))
            self.assertGreater(checked['terminal_outcome_checks'],0)
            self.assertEqual(g.root.actor,1)
            self.assertAlmostEqual(sum(g.measure(g.uniform_policy())['policy_payoffs']),0)

    def test_folded_prefix_dead_money_keeps_its_seat_and_has_no_assumed_hidden_hand(self):
        g=TurnGame(BOARD,[[('AhAd',1)],[],[('QhQd',1)]],pot=60,
                   initial_contributions=(20,20,20),stacks=(40,40,40),folded=(1,),
                   turn_actions=((0,'bet',10),(1,'fold',None)),min_bet=5,
                   turn_bet_sizes=(10,),turn_raise_sizes=(20,),turn_max_raises=1,
                   river_bet_sizes=(10,),river_raise_sizes=(20,),river_max_raises=1)
        self.assertEqual(g.root.actor,2)
        self.assertEqual(g.root.alive,(0,2))
        self.assertTrue(all(h[1] is None for h,_,_,_ in g.outcomes))
        compare_every_path(g)

    def test_prefix_ev_adds_sunk_turn_chips_and_matches_policy_accounting(self):
        g=self.game(turn_actions=((0,'bet',5),(1,'raise',10)),turn_raise_sizes=(20,))
        policy=g.uniform_policy();metrics=g.measure(policy)
        values=g.root_action_values(policy,g.ranges[0][0][0])
        self.assertEqual(values['sunk_chips'],25)
        self.assertAlmostEqual(values['policy_ev_chips'],metrics['policy_payoffs'][0]+25)
        self.assertAlmostEqual(next(r['ev_chips'] for r in values['actions'] if r['action']=='FOLD'),0)
        # Current decision pot, not the pre-turn pot, is the metric denominator.
        self.assertAlmostEqual(metrics['max_unilateral_gain_pct_pot'],max(metrics['unilateral_gains'])/55*100)

    def test_future_river_still_hidden_after_observed_prefix_and_raises(self):
        g=self.game(turn_actions=((0,'check',None),(1,'bet',10)))
        self.assertEqual(g.key(g.root,0),g.key(g.root,1))
        reveal=follow(g,'CALL')
        self.assertNotEqual(g.key(reveal.children[0],0),g.key(reveal.children[0],1))
        self.assertNotIn(g.outcomes[0][1],repr(g.root.history))

    def test_native_and_reference_match_after_observed_raise(self):
        try:load_library()
        except RuntimeError as error:self.skipTest(str(error))
        g=self.game(turn_actions=((0,'bet',5),(1,'raise',10)),turn_raise_sizes=(20,),stack=30)
        python=g.train(6)
        native=g.train(6,method='cfr_plus_native')
        self.assertEqual(set(python),set(native))
        for key,row in python.items():
            for a,b in zip(row,native[key]):self.assertAlmostEqual(a,b,places=11)

    def test_invalid_prefix_caps_and_budget_fail_without_partial_result(self):
        for config in ({'turn_max_raises':True},{'river_max_raises':4},{'turn_raise_sizes':(0,)},
                       {'turn_raise_sizes':(10,10)},{'turn_actions':((1,'bet',10),)},
                       {'turn_actions':((0,'bet',10),(1,'check',None))},
                       {'turn_actions':((0,'bet',10),(1,'call',9))},
                       {'turn_actions':((0,'bet',10),(1,'raise',15))},
                       {'turn_actions':((0,'fold',None),)},
                       {'max_nodes':20,'turn_max_raises':3,'river_max_raises':3}):
            with self.subTest(config=config),self.assertRaises(ValueError):self.game(**config)
