import os
from email.message import Message
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from app.services import river_lessons


class PackagedRiverTests(unittest.TestCase):
    def tearDown(self):
        river_lessons.stop_river_lessons()

    def test_staging_flag_checks_kernel_before_starting_queue(self):
        service=Mock();service.catalog.return_value={"enabled":True}
        with patch.dict(os.environ,{'POKER_RIVER_LESSONS_ENABLED':'1'}), \
             patch('research.native_cfr.load_library') as load, \
             patch('research.river_lessons.RiverLessons',return_value=service) as create:
            self.assertTrue(river_lessons.start_river_lessons());load.assert_called_once();create.assert_called_once()
            self.assertTrue(river_lessons.catalog()['enabled'])
            river_lessons.stop_river_lessons();service.close.assert_called_once()

    def test_missing_kernel_cannot_advertise_an_enabled_feature(self):
        with patch.dict(os.environ,{'POKER_RIVER_LESSONS_ENABLED':'1'}), \
             patch('research.native_cfr.load_library',side_effect=RuntimeError('bad kernel')), \
             patch('research.river_lessons.RiverLessons') as create:
            with self.assertLogs('app.services.river_lessons',level='WARNING'):
                self.assertFalse(river_lessons.start_river_lessons())
            create.assert_not_called()
            self.assertFalse(river_lessons.catalog()['enabled'])
            self.assertEqual(river_lessons.catalog()['reason'],'LESSON_ENGINE_UNAVAILABLE')

    def test_explicit_off_overrides_legacy_local_flag(self):
        with patch.dict(os.environ,{'POKER_RIVER_LESSONS_ENABLED':'0','POKER_LOCAL_RIVER_LESSONS':'1'}), \
             patch('research.native_cfr.load_library') as load:
            self.assertFalse(river_lessons.start_river_lessons());load.assert_not_called()
        env=dict(os.environ);env.pop('POKER_RIVER_LESSONS_ENABLED',None);env.pop('POKER_LOCAL_RIVER_LESSONS',None);env.pop('POKER_LOCAL_TRAINER_SHADOW',None)
        result=subprocess.run([sys.executable,'-c','import app.main,sys;assert not any(m=="research" or m.startswith("research.") for m in sys.modules)'],
                              env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)


class StagingProbeTests(unittest.TestCase):
    def test_edge_vary_fields_are_combined_without_losing_authorization(self):
        from backend.tests.river_staging_smoke import response_headers
        headers=Message();headers['Vary']='Authorization, Origin';headers['Vary']='Accept-Encoding'
        headers['Cache-Control']='private, no-store'
        combined=response_headers(headers)
        self.assertEqual(combined['vary'],'Authorization, Origin, Accept-Encoding')
        self.assertEqual(combined['cache-control'],'private, no-store')

    def test_probe_rejects_other_hosts_before_any_request(self):
        from backend.tests.river_staging_smoke import check
        for url in ('https://example.com','http://poker-ai-coach-api.onrender.com','https://poker-ai-coach-api.onrender.com.evil.test'):
            with self.assertRaises(ValueError):check(url)
