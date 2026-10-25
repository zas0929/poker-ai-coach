"""Independent parity checks for exact factored turn storage, training and evaluation."""
from array import array
import copy
import ctypes as C
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.build_turn_kernel import load_library
from research.custom_river import demo_ranges
from research.turn_reference import TurnGame
from research.turn_packed import Policy,library
from research.turn_oracle import compare_every_path

BOARD=['2c','4d','7h','9s']


class FactoredTurnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:load_library()
        except RuntimeError as error:cls.skipTest(cls,str(error))

    def pair(self,n=2,ranges=None,board=BOARD,**kw):
        spec=dict(pot=20*n,initial_contributions=[20]*n,stack=20,min_bet=5,
                  turn_bet_sizes=[5],turn_raise_sizes=[10],turn_max_raises=1,
                  river_bet_sizes=[5],river_raise_sizes=[10],river_max_raises=1)
        spec.update(kw);ranges=demo_ranges(n) if ranges is None else ranges
        return TurnGame(board,ranges,**spec),TurnGame(board,ranges,**spec,utility_storage='factored')

    def assert_same(self,a,b,iterations=3):
        uniform_a=a.measure(a.uniform_policy());uniform_b=b.measure(b.uniform_policy())
        for name in ('policy_payoffs','best_response_payoffs'):
            for v,w in zip(uniform_a[name],uniform_b[name]):self.assertAlmostEqual(v,w,places=9)
        x=a.train(iterations,method='cfr_plus_native');y=b.train(iterations,method='cfr_plus_native')
        self.assertEqual(set(x),set(y))
        for key,row in x.items():
            for old,new in zip(row,y[key]):self.assertAlmostEqual(old,new,places=10)
        old,new=a.measure(x),b.measure(y)
        for metric in ('policy_payoffs','best_response_payoffs','unilateral_gains'):
            for v,w in zip(old[metric],new[metric]):self.assertAlmostEqual(v,w,places=9)
        if a.root.actor>=0:
            for hand,_ in a.ranges[a.root.actor]:
                old=a.root_action_values(x,hand);new=b.root_action_values(y,hand)
                self.assertAlmostEqual(old['conditional_mass'],new['conditional_mass'],places=10)
                self.assertAlmostEqual(old['policy_ev_chips'],new['policy_ev_chips'],places=9)
                for v,w in zip(old['actions'],new['actions']):
                    self.assertEqual(v['action'],w['action'])
                    self.assertAlmostEqual(v['ev_chips'],w['ev_chips'],places=9)
        return y

    def test_full_private_uncertainty_prefix_raises_and_river_reveal_match(self):
        a,b=self.pair(turn_actions=((0,'bet',5),(1,'raise',10)),turn_raise_sizes=[20],stack=30)
        policy=self.assert_same(a,b,6)
        first=next(d for d,(h,r,_,_) in enumerate(b.outcomes) if h[0]==b.ranges[0][0][0])
        other=next(d for d,(h,r,_,_) in enumerate(b.outcomes) if h==b.outcomes[first][0] and r!=b.outcomes[first][1])
        self.assertEqual(b.key(b.root,first),b.key(b.root,other))
        call=b.root.children[b.root.actions.index('CALL')].children[0]
        self.assertNotEqual(b.key(call,first),b.key(call,other))
        self.assertIsInstance(policy,Policy)

    def test_two_to_six_seats_and_private_uncertainty_at_six_are_not_heads_up_reductions(self):
        for n in range(2,7):
            ranges=[r[:1] for r in demo_ranges(n)]
            a,b=self.pair(n,ranges,stack=2,min_bet=2,turn_bet_sizes=[2],turn_raise_sizes=[],
                          turn_max_raises=0,river_bet_sizes=[2],river_raise_sizes=[],river_max_raises=0)
            self.assert_same(a,b)
        ranges=[[(r[0][0],1),('8c8d',1)] for r in demo_ranges(6)]
        a,b=self.pair(6,ranges,stack=2,min_bet=2,turn_bet_sizes=[2],turn_raise_sizes=[],
                     turn_max_raises=0,river_bet_sizes=[2],river_raise_sizes=[],river_max_raises=0)
        self.assert_same(a,b)

    def test_short_allins_cumulative_reopening_and_future_street_cap(self):
        a,b=self.pair(4,[r[:1] for r in demo_ranges(4)],stacks=[200,60,80,200],
            turn_actions=((0,'bet',40),(1,'raise',60),(2,'raise',80),(3,'call',80)),
            turn_raise_sizes=[120],river_bet_sizes=[],river_raise_sizes=[],river_max_raises=0)
        self.assertIn('RAISE 120',b.root.actions);self.assert_same(a,b)
        compare_every_path(b,(0,len(b.outcomes)-1))

    def test_native_reused_payoffs_equal_python_settlement_with_sidepots_ties_odd_chips_and_refunds(self):
        cases=[
            self.pair(3,[[('2c3c',1)],[('2d3d',1)],[('2h3h',1)]],
                      board=['Ac','Kd','Qh','Js'],pot=3,initial_contributions=[1]*3,
                      stacks=[3,5,7],min_bet=1,turn_bet_sizes=[2],turn_raise_sizes=[4],
                      river_bet_sizes=[1],river_raise_sizes=[],river_max_raises=0)[1],
            self.pair(3,[[('AhAd',1)],[],[('QhQd',1)]],
                      folded=[1],stacks=[8,12,16],turn_actions=((0,'bet',5),(1,'fold',None)),
                      turn_raise_sizes=[10],river_raise_sizes=[],river_max_raises=0)[1]]
        for game in cases:
            library(game);packed=game.packed;native=packed['native']
            for node_index,node in enumerate(game.nodes):
                if node.actor!=-1:continue
                state=packed['arrays']['term'][node_index]
                for d in range(len(game.outcomes)):
                    rank=packed['arrays']['rank'][d]
                    start=(state*native.k+rank)*game.n
                    self.assertEqual(tuple(packed['utility'][start:start+game.n]),game.utilities[(id(node),d)])
            compare_every_path(game,(0,len(game.outcomes)-1))

    def test_zero_decisions_and_forced_checks_have_valid_empty_native_policies(self):
        a,b=self.pair(stack=0)
        policy=self.assert_same(a,b)
        self.assertEqual(len(policy.data),0)
        a,b=self.pair(turn_bet_sizes=[],turn_raise_sizes=[],turn_max_raises=0,
                      river_bet_sizes=[],river_raise_sizes=[],river_max_raises=0)
        self.assert_same(a,b)

    def test_read_only_policy_and_bad_values_cannot_reuse_a_cached_approved_result(self):
        _,game=self.pair()
        policy=game.train(3,method='cfr_plus_native')
        with self.assertRaises(TypeError):policy.data[0]=float('nan')
        bad=Policy(game,array('d',[float('nan')])*len(policy.data))
        with self.assertRaises(ValueError):game.measure(bad)
        with self.assertRaises(ValueError):game.measure({})
        other=copy.copy(game)
        with self.assertRaises(ValueError):other.measure(policy)

    def test_visit_and_storage_limits_refuse_partial_outputs(self):
        _,game=self.pair()
        with self.assertRaisesRegex(ValueError,'budget'):game.train(100,method='cfr_plus_native',max_visits=1)
        with self.assertRaisesRegex(ValueError,'budget'):
            self.pair(max_work=1)
        with self.assertRaises(ValueError):
            TurnGame(BOARD,demo_ranges(2),utility_storage='factored')

    def test_native_validation_rejects_bad_layout_before_traversal(self):
        _,game=self.pair()
        lib=library(game);native=game.packed['native'];old=native.r
        native.r=99
        try:self.assertNotEqual(lib.poker_turn_utilities(C.byref(native)),0)
        finally:native.r=old
        index=next(i for i,v in enumerate(game.packed['arrays']['base']) if v>=0)
        old=game.packed['arrays']['base'][index];game.packed['arrays']['base'][index]=old+1
        try:self.assertNotEqual(lib.poker_turn_utilities(C.byref(native)),0)
        finally:game.packed['arrays']['base'][index]=old

    def test_missing_or_stale_manifest_never_triggers_automatic_compilation(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'absent.so'
            with patch.dict(os.environ,{'POKER_TURN_NATIVE_LIB':str(path)}):
                with self.assertRaises(RuntimeError):load_library()
                self.assertEqual(list(Path(root).iterdir()),[])
                path.write_bytes(b'stale-kernel')
                path.with_suffix(path.suffix+'.json').write_text(json.dumps({'abi':1}))
                with self.assertRaises(RuntimeError):load_library()
                self.assertEqual(path.read_bytes(),b'stale-kernel')
