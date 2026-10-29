import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pathquill.core import Refused
from pathquill.daemon import main
class DaemonExitTests(unittest.TestCase):
    def test_sealed_store_permanent_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=Path(tmp)/'config.json';config.write_text('[]');stderr=io.StringIO()
            with patch('sys.argv',['pathquill','--root',tmp,'--config',str(config)]),patch('pathquill.daemon.serve',side_effect=Refused('store_sealed')),contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as failure:main()
            self.assertEqual(failure.exception.code,78);self.assertEqual(stderr.getvalue(),'store_sealed\n')
    def test_other_refusal_not_misclassified_as_sealed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=Path(tmp)/'config.json';config.write_text('[]')
            with patch('sys.argv',['pathquill','--root',tmp,'--config',str(config)]),patch('pathquill.daemon.serve',side_effect=Refused('writer_busy')):
                with self.assertRaisesRegex(Refused,'writer_busy'):main()
