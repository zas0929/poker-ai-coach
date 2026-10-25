import os
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
