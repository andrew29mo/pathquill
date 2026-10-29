import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from tools.supervision import run_group
ROOT=Path(__file__).resolve().parents[1]
class RunnerTests(unittest.TestCase):
    def test_invalid_mode_invalidates_prior_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            shutil.copytree(ROOT/'tools',root/'tools',ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(ROOT/'pathquill',root/'pathquill',ignore=shutil.ignore_patterns('__pycache__'))
            (root/'evidence').mkdir();out=root/'evidence/capacity.json';out.write_text('{"passed":true}')
            result=subprocess.run([sys.executable,str(root/'tools/capacity.py')],capture_output=True,timeout=5)
            self.assertNotEqual(result.returncode,0);self.assertFalse(json.loads(out.read_text())['passed'])
    def test_timeout_stops_descendant_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'heartbeat'
            child="import time,sys;f=open(sys.argv[1],'a',buffering=1)\nwhile True:f.write('x');time.sleep(.01)"
            worker="import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]);time.sleep(60)"
            with self.assertRaises(subprocess.TimeoutExpired):run_group([sys.executable,'-c',worker,child,str(path)],.4)
            size=path.stat().st_size;time.sleep(.08);self.assertEqual(path.stat().st_size,size)

    def test_busy_unmount_retries_with_bound(self):
        from unittest.mock import patch
        from tools.supervision import unmount
        busy=subprocess.CompletedProcess(['umount','x'],32,stderr='target is busy')
        good=subprocess.CompletedProcess(['umount','x'],0,stderr='')
        with patch('tools.supervision.subprocess.run',side_effect=[busy,good]) as run,patch('tools.supervision.time.sleep'):
            unmount('x');self.assertEqual(run.call_count,2)
        with patch('tools.supervision.subprocess.run',return_value=busy) as run,patch('tools.supervision.time.sleep'):
            with self.assertRaises(subprocess.CalledProcessError):unmount('x')
            self.assertEqual(run.call_count,10)
    def test_unmount_permission_error_is_not_retried(self):
        from unittest.mock import patch
        from tools.supervision import unmount
        denied=subprocess.CompletedProcess(['umount','x'],32,stderr='permission denied')
        with patch('tools.supervision.subprocess.run',return_value=denied) as run:
            with self.assertRaises(subprocess.CalledProcessError):unmount('x')
            self.assertEqual(run.call_count,1)
