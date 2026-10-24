import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from research.custom_river import RiverGame
from research.benchmark_expanded import make_case
from research.strategy_abstraction import hand_groups,StrategyView
from research.fused_best_response import evaluate_policy
from research.adaptive_strategy import propose_split
from research.indexed_split import propose_split_indexed
from research.adaptive_strategy_fast import train_adaptive_fast
from research.adaptive_strategy_indexed import train_adaptive_indexed

BOARD=['2c','4d','7h','9s','Jc']


class IndexedSplitTests(unittest.TestCase):
    def test_matches_selector_and_row_limits_two_to_six_players(self):
        for n in range(2,7):
            spec=make_case('test',BOARD,[3]*n,211+n)['input'];spec.update(raise_sizes=[],max_raises=0)
            game=RiverGame(**spec);mapping=hand_groups(game,'equity_2')
            policy=game.train(10,method='cfr_plus_indexed');_,records=evaluate_policy(game,policy)
            for cap in (len(game.keys),len(game.keys)*3//4,1):
                self.assertEqual(propose_split(game,mapping,records,8,cap),propose_split_indexed(game,mapping,records,8,cap))

    def test_irregular_history_supports_and_label_collision(self):
        h0=();h1=((1,'CALL'),);h2=((1,'BET 10'),)
        keys={(0,'A',h0),(0,'B',h0),(0,'B',h1),(0,'C',h2)}
        game=SimpleNamespace(n=2,keys=keys,action_counts={k:2 for k in keys},nodes=[],root=None,deals=[],utilities={})
        mapping=[{'A':'g','B':'g','C':'g/split0'},{}]
        records={(0,'A',h0):{'q':[10.,0.]},(0,'B',h0):{'q':[0.,10.]}}
        for cap in (3,4,5):
            a=propose_split(game,mapping,records,8,cap);b=propose_split_indexed(game,mapping,records,8,cap)
            self.assertEqual(a,b)
        self.assertEqual(b['grouped_strategy_rows'],4)
        self.assertEqual(b['mapping'][0]['A'],'g/split1')

    def test_builds_only_one_strategy_view_and_preserves_inputs(self):
        spec=make_case('test',BOARD,[8,8],17)['input'];spec.update(raise_sizes=[],max_raises=0)
        game=RiverGame(**spec);mapping=hand_groups(game,'equity_2')
        _,records=evaluate_policy(game,game.train(20,method='cfr_plus_indexed'))
        before=copy.deepcopy((mapping,records));counts={'old':0,'new':0}
        def old(*args):counts['old']+=1;return StrategyView(*args)
        def new(*args):counts['new']+=1;return StrategyView(*args)
        with patch('research.adaptive_strategy.StrategyView',side_effect=old):a=propose_split(game,mapping,records,8,len(game.keys))
        with patch('research.indexed_split.StrategyView',side_effect=new):b=propose_split_indexed(game,mapping,records,8,len(game.keys))
        self.assertEqual(a,b);self.assertGreater(counts['old'],1);self.assertEqual(counts['new'],1)
        self.assertEqual((mapping,records),before)

    def test_cached_partition_keeps_history_specific_scores_and_tie_threshold(self):
        h0=();h1=((1,'CALL'),)
        keys={(0,h,history) for h in ('A','B') for history in (h0,h1)}
        game=SimpleNamespace(n=2,keys=keys,action_counts={k:2 for k in keys},nodes=[],root=None,deals=[],utilities={})
        mapping=[{'A':'g','B':'g'},{}]
        for delta,expected in ((1e-13,h0),(1.,h1)):
            records={(0,'A',h0):{'q':[5.,0.]},(0,'B',h0):{'q':[0.,5.]},
                     (0,'A',h1):{'q':[5.+delta,0.]},(0,'B',h1):{'q':[0.,5.+delta]}}
            a=propose_split(game,mapping,records,8,4);b=propose_split_indexed(game,mapping,records,8,4)
            self.assertEqual(a,b);self.assertEqual(b['history'],expected)

    def test_full_adaptive_traces_and_refusals_match(self):
        spec=make_case('test',BOARD,[8,8],17)['input'];spec.update(raise_sizes=[],max_raises=0)
        game=RiverGame(**spec)
        for change in ({'max_splits':0},{'max_splits':6},{'max_groups_per_seat':2},{'max_strategy_rows':1}):
            args={'iterations':50,'max_strategy_rows':len(game.keys)*3//4,'method':'cfr_plus_indexed',**change}
            self.assertEqual(train_adaptive_fast(game,**args),train_adaptive_indexed(game,**args))
