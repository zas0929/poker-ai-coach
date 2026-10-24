import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from research.custom_river import RiverGame,demo_ranges
from research.build_native import build,default_library
from research.native_cfr import load_library

BOARD=['2c','4d','7h','9s','Jc']


class CompactUtilityTests(unittest.TestCase):
    def test_every_payoff_matches_dict_with_folds_and_sidepots(self):
        spec=dict(board=BOARD,ranges=[[],*demo_ranges(2)],folded=(0,),pot=150,
                  stacks=(500,30,100),initial_contributions=(30,60,60),
                  bet_sizes=(40,),raise_sizes=(80,),max_raises=1)
        left=RiverGame(**spec);right=RiverGame(**spec,utility_storage='compact')
        terminals_left=[n for n in left.nodes if n.actor==-1]
        terminals_right=[n for n in right.nodes if n.actor==-1]
        self.assertEqual(len(left.utilities),len(right.utilities))
        for a,b in zip(terminals_left,terminals_right):
            for d in range(len(left.deals)):
                self.assertEqual(left.utilities[(id(a),d)],right.utilities[(id(b),d)])
        self.assertEqual(len(right.utilities.data)*8,len(right.utilities)*right.n*8)
        with self.assertRaises(KeyError):right.utilities[(id(terminals_right[0]),-1)]
        with self.assertRaises(ValueError):RiverGame(BOARD,demo_ranges(2),utility_storage='unknown')


class NativeCfrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (shutil.which('clang++') or shutil.which('g++')):raise unittest.SkipTest('Local C++ compiler unavailable')
        if not default_library().is_file():build()
        load_library()

    def equivalent(self,spec,iterations=20):
        left=RiverGame(**spec);right=RiverGame(**spec,utility_storage='compact')
        a=left.train(iterations,method='cfr_plus_indexed');b=right.train(iterations,method='cfr_plus_native')
        self.assertEqual(set(a),set(b))
        for key,row in a.items():
            for x,y in zip(row,b[key]):self.assertAlmostEqual(x,y,places=11)
        lm=left.measure(a);rm=right.measure(b)
        for metric in ('policy_payoffs','best_response_payoffs','unilateral_gains'):
            for x,y in zip(lm[metric],rm[metric]):self.assertAlmostEqual(x,y,places=9)
        return right,b

    def test_two_to_six_seats_and_six_actions(self):
        for n in range(2,7):
            self.equivalent(dict(board=BOARD,ranges=demo_ranges(n) if n<=3 else [r[:1] for r in demo_ranges(n)],
                                 bet_sizes=(25,50),raise_sizes=(100,),max_raises=1),4)
        self.equivalent(dict(board=BOARD,ranges=demo_ranges(2),bet_sizes=(10,),raise_sizes=(20,40,60,80),max_raises=1))

    def test_collisions_short_raises_and_dead_money(self):
        self.equivalent(dict(board=BOARD,ranges=[[('AhAd',1),('QhQd',.2)],[('AhAd',.5),('KhKd',1)]],
                             bet_sizes=(25,50),raise_sizes=(100,),max_raises=1),100)
        self.equivalent(dict(board=BOARD,ranges=[[],*demo_ranges(2)],folded=(0,),pot=150,
                             stacks=(500,45,100),initial_contributions=(30,60,60),
                             bet_sizes=(40,),raise_sizes=(80,100),max_raises=2))
        self.equivalent(dict(board=BOARD,ranges=[r[:1] for r in demo_ranges(4)],pot=240,
                             stacks=(200,60,80,200),initial_contributions=(60,)*4,
                             bet_sizes=(40,),raise_sizes=(60,80,120),max_raises=3))

    def test_nonempty_public_prefix_with_short_raises_and_fold(self):
        game,policy=self.equivalent(dict(board=BOARD,ranges=demo_ranges(3),pot=300,
            initial_contributions=(100,100,100),stacks=(200,200,60),dealer=0,
            river_actions=((1,'bet',40),(2,'raise',60),(0,'call',60)),
            bet_sizes=(40,),raise_sizes=(100,120),max_raises=2))
        self.assertEqual(game.root.actions,('FOLD','CALL'))
        self.assertIn((game.root.actor,game.ranges[game.root.actor][0][0],game.root.history),policy)
        self.equivalent(dict(board=BOARD,ranges=[demo_ranges(3)[0],[],demo_ranges(3)[2]],
            folded=(1,),pot=300,initial_contributions=(100,)*3,stacks=(200,200,200),dealer=0,
            river_actions=((1,'check',None),(2,'bet',40),(0,'raise',80),(1,'fold',None)),
            bet_sizes=(40,),raise_sizes=(120,),max_raises=1))

    def test_terminal_tie_and_repeated_native_calls(self):
        game,policy=self.equivalent(dict(board=['As','Ks','Qs','Js','Ts'],ranges=[[('2h2d',1)],[('3h3d',1)]],
                                          stacks=(0,0),pot=3,initial_contributions=(1,2),bet_sizes=(1,)))
        self.assertEqual(policy,{})
        game,policy=self.equivalent(dict(board=BOARD,ranges=demo_ranges(2)))
        self.assertEqual(policy,game.train(20,method='cfr_plus_native'))
        for bad in (True,0,1.5,2001):
            with self.assertRaises(ValueError):game.train(bad,method='cfr_plus_native')
        with self.assertRaises(ValueError):RiverGame(BOARD,demo_ranges(2)).train(2,method='cfr_plus_native')

    def test_wider_ranges_and_live_odd_chip_decisions(self):
        from research.benchmark_expanded import scenarios
        cases=list(scenarios())
        for case in (cases[0],next(c for c in cases if c['name']=='wide_2_4096')):
            self.equivalent(case['input'],5)
        self.equivalent(dict(board=['As','Ks','Qs','Js','Ts'],ranges=[[],*demo_ranges(2)],
                             folded=(0,),stacks=(500,50,50),pot=5,initial_contributions=(1,2,2),
                             dealer=0,bet_sizes=(10,),raise_sizes=(20,),max_raises=1))

    def test_missing_or_stale_binary_never_silently_falls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'missing.dylib'
            with patch.dict(os.environ,{'POKER_RESEARCH_NATIVE_LIB':str(path)}):
                with self.assertRaises(RuntimeError):load_library()
            shutil.copy(default_library(),path)
            with patch.dict(os.environ,{'POKER_RESEARCH_NATIVE_LIB':str(path)}):
                with self.assertRaises(RuntimeError):load_library()
            manifest=json.loads(default_library().with_suffix(default_library().suffix+'.json').read_text())
            manifest['source_sha256']='stale'
            path.with_suffix(path.suffix+'.json').write_text(json.dumps(manifest))
            with patch.dict(os.environ,{'POKER_RESEARCH_NATIVE_LIB':str(path)}):
                with self.assertRaises(RuntimeError):load_library()
