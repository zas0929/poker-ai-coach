import json
from pathlib import Path
import tempfile
import unittest
from research.validate_reallocation_cycle import cases,write_manifest,load_manifest,FROZEN_CYCLE_SHA,fault_runner,compact
from research.custom_river import RiverGame
from unittest.mock import patch


class CycleValidationTests(unittest.TestCase):
    def test_new_corpus_reproducible_and_raises_fit_stacks(self):
        rows=list(cases());self.assertEqual(rows,list(cases()));self.assertEqual(len(rows),30)
        self.assertEqual({r['seed'] for r in rows},{503,907})
        self.assertEqual(len({r['name'] for r in rows}),30)
        for r in rows:
            s=r['input'];self.assertEqual(sum(s['initial_contributions']),s['pot'])
            self.assertTrue(all(v<=max(s['stacks']) for v in s['raise_sizes']))
            if r['family']=='sidepot_or_tie' and r['dealt_players']>=4:self.assertEqual(s['ranges'][-1],[])
        for family in ('sizing','short_raise','sidepot_or_tie'):
            sample=next(r for r in rows if r['family']==family);self.assertGreater(len(RiverGame(**sample['input']).deals),0)

    def test_manifest_immutable_and_source_frozen(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'plan.json';write_manifest(path)
            value=load_manifest(path);self.assertEqual(value['sources']['reallocation_cycle.py'],FROZEN_CYCLE_SHA)
            value['limits']['total_seconds']=90;path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):load_manifest(path)
            with self.assertRaises(ValueError):write_manifest(path)

    def test_faults_apply_only_to_trials(self):
        for fault in ('trial_timeout','trial_memory'):
            with patch('research.validate_reallocation_cycle.run_guarded',return_value={'status':'timed_out'}) as fn:
                runner=fault_runner(fault);runner({'kind':'baseline'},100,40,128)
                self.assertEqual(fn.call_args.args[2:],(40,128))
                runner({'kind':'trial'},100,40,128)
                self.assertEqual(fn.call_args.args[2:],(.001,128) if fault=='trial_timeout' else (40,1))

    def test_compaction_keeps_hash_and_metrics_without_policy_duplication(self):
        cp={'policy':[[0,'AhAd',[],[.5,.5]]],'metrics':{'gain':1},'rows':2}
        r=compact({'baseline':{'checkpoint':cp},'best_checkpoint':cp,'attempts':[]})
        self.assertNotIn('policy',r['best_checkpoint'])
        self.assertEqual(r['baseline']['checkpoint']['policy_sha256'],r['best_checkpoint']['policy_sha256'])
        self.assertEqual(r['best_checkpoint']['metrics'],{'gain':1})
