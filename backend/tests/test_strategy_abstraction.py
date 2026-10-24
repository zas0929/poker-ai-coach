import copy
import unittest
from research.custom_river import RiverGame
from research.strategy_abstraction import StrategyView,hand_groups,lift_policy,train_abstract
from research.benchmark_strategy_abstraction import root_diagnostic,summarize
from research.benchmark_expanded import make_case

BOARD=['2c','4d','7h','9s','Jc']


def game():
    return RiverGame(BOARD,[[('AhAd',1.),('QhQd',3.)],[('KhKd',2.),('6h6d',1.)]],
                     bet_sizes=[20],raise_sizes=[40],max_raises=1,max_joint_combos=64)


class StrategyAbstractionTests(unittest.TestCase):
    def test_identity_matches_unrestricted_cfr_without_touching_chance(self):
        source=game();deals=copy.deepcopy(source.deals)
        baseline=source.train(50,method='cfr_plus_indexed')
        abstract,evidence=train_abstract(source,'identity',50,method='cfr_plus_indexed')
        self.assertEqual(baseline,abstract);self.assertEqual(source.deals,deals)
        self.assertEqual(evidence['grouped_strategy_rows'],len(source.keys))
        self.assertFalse(evidence['live_advice_allowed'])

    def test_grouping_ties_only_strategy_rows_and_preserves_weights_and_utilities(self):
        source=game();view=StrategyView(source,hand_groups(source,'category'))
        self.assertIs(view.deals,source.deals);self.assertIs(view.utilities,source.utilities)
        self.assertIs(view.nodes,source.nodes)
        self.assertLess(len(view.keys),len(source.keys))
        policy,evidence=train_abstract(source,'category',50,method='cfr_plus_indexed')
        for node in source.nodes:
            if node.actor==-1:continue
            bygroup={}
            for key in source.keys:
                if key[0]!=node.actor or key[2]!=node.history:continue
                label=view.mapping[key[0]][key[1]]
                if label in bygroup:self.assertEqual(policy[key],bygroup[label])
                bygroup[label]=policy[key]
        source.measure(policy)  # Must be a complete normalized original-game policy.
        self.assertTrue(evidence['original_deals_preserved'])

    def test_unrestricted_best_response_can_distinguish_hands_in_same_group(self):
        source=RiverGame(BOARD,[[('AhAd',1.),('QhQd',1.)],[('KhKd',1.)]],bet_sizes=[50],max_raises=0)
        view=StrategyView(source,hand_groups(source,'category'))
        tied={}
        for key,count in view.action_counts.items():
            node=next(n for n in source.nodes if n.actor==key[0] and n.history==key[2])
            wanted='CHECK' if 'CHECK' in node.actions else 'CALL'
            tied[key]=[float(a==wanted) for a in node.actions]
        lifted=lift_policy(source,view,tied);measured=source.measure(lifted)
        # Strong and weak pair share a category, but the original BR may play
        # them differently. A grouped-only BR would hide this loss.
        self.assertGreater(measured['unilateral_gains'][0],20.)

    def test_invalid_mapping_and_policy_fail_closed(self):
        source=game();mapping=hand_groups(source,'category')
        del mapping[0]['AhAd']
        with self.assertRaises(ValueError):StrategyView(source,mapping)
        view=StrategyView(source,hand_groups(source,'category'))
        with self.assertRaises(ValueError):lift_policy(source,view,{})
        bad={k:[float('nan')]*count for k,count in view.action_counts.items()}
        with self.assertRaises(ValueError):lift_policy(source,view,bad)
        with self.assertRaises(ValueError):hand_groups(source,'auto_best')
        with self.assertRaises(ValueError):train_abstract(source,'category',10,method='unknown')

    def test_two_to_six_seats_keep_complete_original_policies(self):
        for n in range(2,7):
            spec=make_case('test',BOARD,[2]*n,17+n)['input'];spec.update(raise_sizes=[],max_raises=0)
            source=RiverGame(**spec)
            for mode in ('category','equity_2','equity_4'):
                policy,_=train_abstract(source,mode,5,method='cfr_plus_indexed')
                self.assertEqual(set(policy),source.keys);source.measure(policy)

    def test_reference_identity_loss_and_refused_baseline_exclusion(self):
        source=game();policy=source.train(30,method='cfr_plus_indexed')
        diagnostic=root_diagnostic(source,policy,policy)
        self.assertAlmostEqual(diagnostic['mean_additional_loss_chips'],0.)
        self.assertEqual(diagnostic['mean_tv'],0.)
        summary=summarize([{'status':'timed_out'},{'status':'completed','baseline_quality_passed':False}])
        self.assertEqual(summary['category']['cases_with_qualified_baseline'],0)
        self.assertIsNone(summary['category']['mean_root_tv'])
