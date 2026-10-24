import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from research.local_shadow_server import main


class LocalShadowServerTests(unittest.TestCase):
    def test_launcher_enables_only_process_flags_and_loopback(self):
        before=dict(os.environ)
        with patch.dict(os.environ,{},clear=False),patch('research.local_shadow_server.load_library') as native,patch('uvicorn.run') as serve:
            main(['--port','8123'])
            native.assert_called_once();serve.assert_called_once_with('app.main:app',host='127.0.0.1',port=8123,workers=1)
            self.assertEqual(os.environ['POKER_LOCAL_TRAINER_SHADOW'],'1')
            self.assertTrue(Path(os.environ['POKER_LOCAL_TRAINER_SHADOW_PLAN']).is_absolute())
        self.assertEqual(dict(os.environ),before)

    def test_bad_plan_port_or_missing_kernel_never_starts_server(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bad.json';path.write_text(json.dumps({'version':2,'mode':'replace_advice'}))
            for arguments in (['--plan',str(path)],['--port','0']):
                with patch('uvicorn.run') as serve,self.assertRaises(SystemExit):main(arguments)
                serve.assert_not_called()
        with patch('research.local_shadow_server.load_library',side_effect=RuntimeError('Build kernel explicitly.')),patch('uvicorn.run') as serve:
            with self.assertRaises(SystemExit):main([])
            serve.assert_not_called()
