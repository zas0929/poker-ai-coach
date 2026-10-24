import copy
import json
from pathlib import Path
import unittest
from research.benchmark_snapshot import control
from research.public_subset_policy import select_public_subset,validate_policy,tree_from_policy
from research.river_snapshot import build_river_from_snapshot,combo_key
from research.trainer_shadow_bridge import TrainerShadowBridge


def policy(width=3):return {'name':'anchored_public_subset_v1','width':width,'seed':20261024,'max_joint_combos':4096}


class PublicSubsetPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.snapshot=control(3,river_actions=[('check',None),('bet',10)])
    def own(self):
        return next(p['range'][20]['cards'] for p in self.snapshot['players'] if p['id']==self.snapshot['actor_id'])

    def test_repeatability_nested_support_original_weights_and_anchor(self):
        own=self.own();small=select_public_subset(self.snapshot,own,policy())
        self.assertEqual(small,select_public_subset(self.snapshot,own,policy()))
        wide=select_public_subset(self.snapshot,own,policy(6))
        self.assertEqual(small[1],own)
        for pid,rows in small[0].items():self.assertEqual(rows,wide[0][pid][:3])
        self.assertTrue(small[2]['actor_anchor'])
        game,_=build_river_from_snapshot(self.snapshot,small[0],bet_sizes=[10],raise_sizes=[40],max_raises=1,max_joint_combos=4096)
        for i,p in enumerate(self.snapshot['players']):
            original={r['cards']:r['weight'] for r in p['range']}
            self.assertEqual(game.ranges[i],[(t,original[t]) for t in small[0][p['id']]])
        self.assertTrue(any(d[0][game.root.actor]==own for d in game.deals))

    def test_opponent_selection_does_not_depend_on_known_own_hand(self):
        first=select_public_subset(self.snapshot,self.own(),policy())[0]
        actor=self.snapshot['actor_id'];other=next(p['range'][21]['cards'] for p in self.snapshot['players'] if p['id']==actor)
        second=select_public_subset(self.snapshot,other,policy())[0]
        for pid in first:
            if pid!=actor:self.assertEqual(first[pid],second[pid])
        self.assertNotEqual(first[actor][0],second[actor][0])

    def test_invalid_policy_and_impossible_budget_do_not_shrink_silently(self):
        for change in ({'width':True},{'width':1},{'width':65},{'seed':-1},{'seed':True},{'max_joint_combos':4097},{'name':'other'}):
            with self.assertRaises(ValueError):validate_policy({**policy(),**change})
        snapshot=control(6)
        actor=next(p for p in snapshot['players'] if p['id']==snapshot['actor_id'])
        with self.assertRaisesRegex(ValueError,'no auto-shrinking'):
            select_public_subset(snapshot,actor['range'][0]['cards'],policy(5))
        with self.assertRaises(ValueError):select_public_subset(self.snapshot,'2x3x',policy())

    def test_tree_uses_blind_units_and_keeps_exact_coach_size(self):
        config={'bet_sizes_bb':[2,4],'raise_sizes_bb':[8,12],'max_raises':1,'include_coach_size':True}
        tree=tree_from_policy(self.snapshot,{'action':'raise','amount':37},config,4096)
        self.assertEqual(tree['bet_sizes'],[20,40]);self.assertEqual(tree['raise_sizes'],[37,80,120])
        self.assertEqual(tree['max_joint_combos'],4096)
        changed=copy.deepcopy(self.snapshot);changed['big_blind']=2
        tree=tree_from_policy(changed,{'action':'check','amount':None},config,4096)
        self.assertEqual(tree['bet_sizes'],[4,8]);self.assertEqual(tree['raise_sizes'],[16,24])

    def test_folded_seats_have_no_selected_range(self):
        snapshot=control(4,'folded',river_actions=[('check',None),('bet',10)])
        actor=next(p for p in snapshot['players'] if p['id']==snapshot['actor_id'])
        selected,_,evidence=select_public_subset(snapshot,actor['range'][0]['cards'],policy())
        self.assertEqual(len(selected),3);self.assertEqual(evidence['raw_combinations'],27)
        self.assertTrue(all(p['id'] not in selected for p in snapshot['players'] if p['status']=='folded'))

    def test_bundled_opt_in_config_is_valid_without_enabling_any_service(self):
        path=Path(__file__).parents[1]/'research/config/local-shadow-policy.json'
        config=json.loads(path.read_text())
        bad=copy.deepcopy(config);bad['mode']='replace_advice'
        with self.assertRaises(ValueError):TrainerShadowBridge(bad)
        bridge=TrainerShadowBridge(config)
        try:self.assertEqual(bridge.policy,policy())
        finally:bridge.close()
