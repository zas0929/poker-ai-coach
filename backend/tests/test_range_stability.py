import copy
import unittest
from research.benchmark_snapshot import control
from research.stratified_subset import NAME,features,probe_hands,select_stratified_subset
from research.benchmark_range_stability import compare
from research.summarize_range_stability import summarize
from research.river_snapshot import build_river_from_snapshot,digest


def policy(width=3):
    return {'name':NAME,'width':width,'seed':17,'max_joint_combos':4096}


def solved(probabilities=(.25,.75), quality=True):
    return {'status':'completed','passes_quality_gate':quality,'actions':['FOLD','CALL'],
            'probabilities':list(probabilities),'reference_action_ev_chips':[0.,20.]}


class StratifiedSubsetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot=control(3,board=['2s','5s','9s','Kh','Ad'],river_actions=[('check',None),('bet',10)])

    def test_features_distinguish_made_hands_and_nut_suit_blocker(self):
        self.assertEqual(features(self.snapshot,'QsJs')['category'],'flush')
        self.assertEqual(features(self.snapshot,'AcAh')['category'],'trips')
        self.assertTrue(features(self.snapshot,'As3c')['nut_suit_blocker'])
        self.assertFalse(features(self.snapshot,'Ks3c')['nut_suit_blocker'])

    def test_nested_repeatable_anchor_and_public_opponents(self):
        own=probe_hands(self.snapshot)[0]['hand'];small=select_stratified_subset(self.snapshot,own,policy())
        self.assertEqual(small,select_stratified_subset(self.snapshot,own,policy()))
        wide=select_stratified_subset(self.snapshot,own,policy(6))
        other=select_stratified_subset(self.snapshot,probe_hands(self.snapshot)[1]['hand'],policy())
        actor=self.snapshot['actor_id'];self.assertEqual(small[1],own)
        for seat,hands in small[0].items():
            self.assertEqual(hands,wide[0][seat][:3])
            if seat!=actor:self.assertEqual(hands,other[0][seat])
        self.assertFalse(small[2]['range_stability_verified'])

    def test_original_weights_survive_and_no_silent_budget_shrinking(self):
        snapshot=copy.deepcopy(self.snapshot)
        for p in snapshot['players']:
            for i,row in enumerate(p['range']):row['weight']=i+1
        snapshot['information_key']=digest({k:v for k,v in snapshot.items() if k!='information_key'})
        own=probe_hands(snapshot)[0]['hand'];selected,_,_=select_stratified_subset(snapshot,own,policy())
        game,_=build_river_from_snapshot(snapshot,selected,bet_sizes=[10],raise_sizes=[],max_raises=0,max_joint_combos=4096)
        for i,p in enumerate(snapshot['players']):
            source={r['cards']:r['weight'] for r in p['range']}
            self.assertEqual(game.ranges[i],[(t,source[t]) for t in selected[p['id']]])
        with self.assertRaisesRegex(ValueError,'no auto-shrinking'):
            select_stratified_subset(snapshot,own,policy(17))
        with self.assertRaises(ValueError):select_stratified_subset(snapshot,own,{**policy(),'name':'unknown'})


class StabilityComparisonTests(unittest.TestCase):
    def test_ev_uses_common_reference_q_not_candidate_payoffs(self):
        candidate=solved();candidate['reference_action_ev_chips']=[999.,-999.]
        result=compare(candidate,solved((0.,1.)),100,10)
        self.assertEqual(result['candidate_ev_in_reference_chips'],15.)
        self.assertEqual(result['first_action_loss_bb'],.5)
        self.assertEqual(result['first_action_loss_pct_pot'],5.)
        self.assertEqual(result['tv'],.25)

    def test_size_change_is_distinct_from_action_kind(self):
        a=solved((1.,0.));b=solved((0.,1.))
        for r in (a,b):r['actions']=['RAISE 40','RAISE 80']
        result=compare(a,b,100,10)
        self.assertFalse(result['same_modes']);self.assertTrue(result['same_action_kinds'])
        self.assertEqual(result['conditional_size_delta_bb'],4.)

    def test_failed_quality_or_refusal_never_counts_as_agreement(self):
        self.assertIsNone(compare(solved(quality=False),solved(),100,10))
        self.assertIsNone(compare(solved(),{'status':'rejected'},100,10))
        wrong=solved();wrong['actions']=['CHECK','BET 10']
        with self.assertRaises(ValueError):compare(solved(),wrong,100,10)

    def test_seed_and_width_comparisons_exclude_failure_and_match_populations(self):
        rows=[]
        for method in ('uniform','stratified'):
            for width in (2,3):
                for seed in (17,31,73):
                    c={**solved(),'method':method,'width':width,'seed':seed}
                    if method=='stratified' and width==2 and seed==17:c['passes_quality_gate']=False
                    comparisons={m:compare(c,solved(),100,10) for m in ('uniform','stratified')}
                    rows.append({'case':'test','probe':'strong','candidate':c,
                                 'comparisons':{m:v for m,v in comparisons.items() if v is not None}})
        report={'results':rows,'seeds':[17,31,73],'candidate_widths':[2,3],'reference_disagreements':[]}
        s=summarize(report)
        self.assertEqual(s['seed_stability']['uniform_2']['pairs'],3)
        self.assertEqual(s['seed_stability']['stratified_2']['pairs'],0)
        self.assertEqual(s['width_stability']['stratified']['pairs'],2)
        self.assertEqual(s['matched_reference_losses']['2']['matched_candidates_per_method'],2)
        for method in ('uniform','stratified'):
            self.assertEqual(s['matched_reference_losses']['2'][method]['comparisons'],4)
