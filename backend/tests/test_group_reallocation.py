import copy
import unittest
from unittest.mock import patch
from research.custom_river import RiverGame
from research.strategy_abstraction import hand_groups,StrategyView
from research.group_reallocation import candidates,project_merge,partition_key,recover_mapping,audit_reallocation
from research.adaptive_strategy_indexed import train_adaptive_indexed
from research.fused_best_response import evaluate_policy

BOARD=['2c','4d','7h','9s','Jc']


class GroupReallocationTests(unittest.TestCase):
    def game(self):return RiverGame(BOARD,[[('AhAd',1.),('QhQd',3.)],[('KhKd',1.)]],bet_sizes=[50])

    def test_identical_strategies_merge_without_changing_policy_or_chance(self):
        game=self.game();mapping=hand_groups(game,'identity')
        policy={k:[1./c]*c for k,c in game.action_counts.items()};before=copy.deepcopy(game.deals)
        c=candidates(game,mapping,policy)[0];merged,projected=project_merge(game,mapping,policy,c)
        self.assertEqual(projected,policy);self.assertEqual(game.deals,before)
        self.assertEqual(len(StrategyView(game,mapping).keys)-len(StrategyView(game,merged).keys),c['freed_rows'])
        self.assertEqual(evaluate_policy(game,policy)[0],evaluate_policy(game,projected)[0])

    def test_projection_uses_original_own_hand_mass_not_equal_group_weights(self):
        game=self.game();mapping=hand_groups(game,'identity')
        policy={k:([1.,0.] if k[1]=='AhAd' else [0.,1.]) if c==2 else [1./c]*c for k,c in game.action_counts.items()}
        c=candidates(game,mapping,policy)[0];_,projected=project_merge(game,mapping,policy,c)
        self.assertEqual(projected[(0,'AhAd',game.root.history)],[.25,.75])
        self.assertEqual(projected[(0,'QhQd',game.root.history)],[.25,.75])
        evaluate_policy(game,projected)

    def test_partition_identity_ignores_labels_and_trace_recovery_is_validated(self):
        self.assertEqual(partition_key([{'A':'x','B':'y'}]),partition_key([{'A':'y','B':'x'}]))
        game=self.game();policy,e=train_adaptive_indexed(game,iterations=10,max_strategy_rows=len(game.keys),method='cfr_plus_indexed')
        mapping=recover_mapping(game,e);self.assertEqual(len(StrategyView(game,mapping).keys),e['history'][-1]['grouped_strategy_rows'])
        bad=copy.deepcopy(e);bad['history'][-1]['grouped_strategy_rows']+=1
        with self.assertRaises(ValueError):recover_mapping(game,bad)

    def test_measured_merge_regression_blocks_resplitting(self):
        game=self.game();policy,e=train_adaptive_indexed(game,iterations=100,max_strategy_rows=len(game.keys),method='cfr_plus_indexed')
        audit=audit_reallocation(game,policy,e,max_candidates=1,max_tv=1.,method='cfr_plus_indexed')
        self.assertEqual(len(audit['trials']),1)
        self.assertGreater(audit['trials'][0]['merge_gain_delta_pct_pot'],0.)
        self.assertEqual(audit['trials'][0]['resplit_status'],'merge_regression')

    def test_resplit_that_only_undoes_merge_is_rejected(self):
        game=self.game();_,e=train_adaptive_indexed(game,iterations=10,max_strategy_rows=len(game.keys),method='cfr_plus_indexed')
        mapping=recover_mapping(game,e);policy={k:[1./c]*c for k,c in game.action_counts.items()}
        with patch('research.group_reallocation.propose_targeted_split',return_value={'mapping':mapping}):
            audit=audit_reallocation(game,policy,e,max_candidates=1,method='cfr_plus_indexed')
        self.assertEqual(audit['trials'][0]['resplit_status'],'undo_rejected')

    def test_audit_obeys_budgets_and_preserves_no_live_advice(self):
        game=self.game();policy,e=train_adaptive_indexed(game,iterations=10,max_strategy_rows=len(game.keys),method='cfr_plus_indexed')
        audit=audit_reallocation(game,policy,e,max_candidates=1,method='cfr_plus_indexed')
        self.assertLessEqual(len(audit['trials']),1);self.assertFalse(audit['live_advice_allowed'])
        for trial in audit['trials']:
            if trial['resplit_status']=='evaluated':self.assertLessEqual(trial['final_rows'],e['limits']['max_strategy_rows'])
        for kw in ({'max_candidates':0},{'max_tv':float('nan')},{'method':'auto'}):
            with self.assertRaises(ValueError):audit_reallocation(game,policy,e,**kw)
