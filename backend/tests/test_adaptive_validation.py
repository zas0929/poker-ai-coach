import copy
import json
from pathlib import Path
import tempfile
import unittest
from research.validate_adaptive_strategy import scenarios,manifest,write_manifest,load_manifest,summarize,FROZEN_ADAPTIVE_SHA
from research.custom_river import RiverGame
from research.sidepot_reference import compare_every_path


class AdaptiveValidationTests(unittest.TestCase):
    def test_corpus_is_reproducible_new_seeds_and_covers_declared_conditions(self):
        cases=list(scenarios());self.assertEqual(cases,list(scenarios()))
        self.assertEqual(len(cases),46);self.assertEqual(len({c['name'] for c in cases}),46)
        self.assertEqual({c['seed'] for c in cases},{101,211})
        self.assertEqual({c['live_players'] for c in cases},{2,3,4,5,6})
        self.assertEqual({c['family'] for c in cases},{'sizing','short_raises','prior_sidepot','folded','board_tie'})
        for c in cases:
            s=c['input'];self.assertEqual(c['row_budget'],'compact')
            if c['family']=='short_raises':
                self.assertEqual(s['max_raises'],1);self.assertEqual(s['stacks'][0],8)
            elif c['family']=='prior_sidepot':
                self.assertEqual(s['stacks'][0],0);self.assertLess(s['initial_contributions'][0],s['initial_contributions'][1])
            elif c['family']=='folded':self.assertEqual(s['ranges'][1],[])

    def test_manifest_freezes_algorithm_settings_and_refuses_overwrite_or_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'plan.json';value=write_manifest(p)
            self.assertEqual(load_manifest(p)['source_sha256']['adaptive_strategy.py'],FROZEN_ADAPTIVE_SHA)
            self.assertEqual(write_manifest(p),value)
            bad=json.loads(p.read_text());bad['quality_gate_pct_pot']=1.
            p.write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError,'hash'):load_manifest(p)
            with self.assertRaisesRegex(ValueError,'overwrite'):write_manifest(p)

    def test_each_family_first_case_has_legal_tree_and_matches_engine_probe(self):
        checked=set();invalid=[]
        for c in scenarios():
            if c['family'] in checked:continue
            try:game=RiverGame(**c['input'])
            except ValueError:
                invalid.append(c['name']);continue
            checked.add(c['family'])
            texts=game.deals[0][0]
            spec={**c['input'],'ranges':[[(t,1.)] if t else [] for t in texts]}
            result=compare_every_path(RiverGame(**spec))
            self.assertGreater(result['terminal_deal_checks'],0)
        self.assertEqual(checked,{'sizing','short_raises','prior_sidepot','folded','board_tie'})
        self.assertEqual(invalid,['short_raises_2_101','short_raises_2_211'])

    def test_oversized_tree_deal_product_remains_a_refusal(self):
        for case in scenarios():
            if case['family']=='board_tie' and case['dealt_players']==6:
                with self.assertRaisesRegex(ValueError,'Tree/deal product'):
                    RiverGame(**case['input'])

    def test_corrected_inputs_are_separate_and_keep_original_algorithm(self):
        from research.supplement_adaptive_validation import plan,write_plan
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)/'base.json';write_manifest(base)
            supplement=Path(directory)/'supplement.json';value=write_plan(supplement,base)
            self.assertEqual(value,plan(base));self.assertEqual(len(value['cases']),2)
            self.assertEqual(value['parent_manifest_sha256'],load_manifest(base)['manifest_sha256'])
            for case in value['cases']:
                self.assertEqual(case['input']['raise_sizes'],[12])
                self.assertEqual(case['input']['max_raises'],1)
                self.assertGreater(len(RiverGame(**case['input']).deals),0)
            self.assertTrue(all(c['input']['raise_sizes']==[20] for c in load_manifest(base)['cases'] if c['family']=='short_raises' and c['dealt_players']==2))
            bad=copy.deepcopy(value);bad['cases'][0]['seed']=17;supplement.write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError,'overwrite'):write_plan(supplement,base)

    def test_summary_never_credits_timeouts_or_unqualified_baselines(self):
        case={'family':'sizing','live_players':2}
        ready={'status':'ready','reason':'quality_passed','history':[{'grouped_strategy_rows':6}], 'original_strategy_rows':8}
        rows=[{'case':case,'status':'completed','baseline_quality_passed':True,'adaptive':ready},
              {'case':case,'status':'completed','baseline_quality_passed':False,'adaptive':ready},
              {'case':case,'status':'timed_out'},
              {'case':case,'status':'completed','baseline_quality_passed':True,'adaptive':{**ready,'status':'rejected','reason':'no_split_within_budget'}}]
        s=summarize(rows)['overall']
        self.assertEqual(s['attempted'],4);self.assertEqual(s['eligible'],2)
        self.assertEqual(s['ready'],1);self.assertEqual(s['baseline_unqualified'],1)
        self.assertEqual(s['adaptive_ready_with_unqualified_baseline'],1)
        self.assertEqual(s['eligible_rejections'],{'no_split_within_budget':1})
        self.assertEqual(s['process_statuses']['timed_out'],1)
