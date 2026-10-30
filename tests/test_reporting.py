import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
class ReportingTests(unittest.TestCase):
    def test_reboot_missing_pointer_invalidates_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'tools').mkdir();(root/'evidence').mkdir()
            shutil.copytree(ROOT/'pathquill',root/'pathquill')
            shutil.copy(ROOT/'tools/reboot.py',root/'tools/reboot.py')
            output=root/'evidence/reboot.json';output.write_text('{"passed":true}')
            result=subprocess.run([sys.executable,str(root/'tools/reboot.py'),'after'],capture_output=True,timeout=5)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(json.loads(output.read_text())['passed'])

    def test_invalid_deployment_invocation_invalidates_prior_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            shutil.copytree(ROOT/'pathquill',root/'pathquill',ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(ROOT/'tools',root/'tools',ignore=shutil.ignore_patterns('__pycache__'))
            (root/'evidence').mkdir();output=root/'evidence/deployment.json';output.write_text('{"passed":true}')
            result=subprocess.run([sys.executable,str(root/'tools/deployment.py'),'invalid'],capture_output=True,timeout=5)
            self.assertNotEqual(result.returncode,0);self.assertFalse(json.loads(output.read_text())['passed'])

    def test_invalid_use_case_invocation_invalidates_prior_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            shutil.copytree(ROOT/'pathquill',root/'pathquill',ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(ROOT/'tools',root/'tools',ignore=shutil.ignore_patterns('__pycache__'))
            (root/'evidence').mkdir();output=root/'evidence/use-case.json';output.write_text('{"passed":true}')
            result=subprocess.run([sys.executable,str(root/'tools/deployment.py'),'orchestrate-use-case','unexpected'],capture_output=True,timeout=5)
            self.assertNotEqual(result.returncode,0);self.assertFalse(json.loads(output.read_text())['passed'])
