"""Execute the actual documented readiness helper under Bash errexit."""
import pathlib,re,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class ManualGuideTests(unittest.TestCase):
    def helper(self):
        text=(ROOT/'docs/USE_CASE.md').read_text()
        return re.search(r'(pq_ready\(\) \{.*?\n\})\nsudo systemctl start',text,re.S).group(1)
    def test_documented_helper_survives_startup_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            script='''set -euo pipefail
pq_private="$1"
pq_calls=0
pq() {
  pq_calls=$((pq_calls+1))
  if [ "$pq_calls" -eq 1 ]; then return 1; fi
  printf '%s' '{"ok":true,"state":"RECORDING","health":{"0":"success"}}'
}
'''+self.helper()+'''\npq_ready healthy
[ "$pq_calls" -eq 2 ]
test -s "$pq_private/status.json"
printf 'READY'
'''
            p=subprocess.run(['bash','-s','--',tmp],input=script,text=True,capture_output=True,timeout=5)
            self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout,'READY')
    def test_documented_helper_fails_closed_when_never_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            script='''set -euo pipefail
pq_private="$1"
pq() { return 1; }
sleep() { :; }
'''+self.helper()+'''\npq_ready healthy
printf 'UNSAFE_CONTINUE'
'''
            p=subprocess.run(['bash','-s','--',tmp],input=script,text=True,capture_output=True,timeout=5)
            self.assertNotEqual(p.returncode,0);self.assertNotIn('UNSAFE_CONTINUE',p.stdout)

    def test_documented_copy_guard_refuses_existing_entries(self):
        text=(ROOT/'docs/USE_CASE.md').read_text()
        guard=re.search(r'(if \[ -e .*?\nfi)\nsudo cp -a',text,re.S).group(1)
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            for kind in ('directory','file','symlink','absent'):
                entry=root/'copied-package'
                if kind=='directory':entry.mkdir()
                elif kind=='file':entry.write_text('preserve')
                elif kind=='symlink':entry.symlink_to(root/'missing')
                script='set -euo pipefail\npq_private="$1"\n'+guard+"\nprintf 'COPY_REACHED'\n"
                p=subprocess.run(['bash','-s','--',tmp],input=script,text=True,capture_output=True,timeout=5)
                if kind=='absent':self.assertEqual(p.returncode,0,p.stderr)
                else:
                    self.assertNotEqual(p.returncode,0);self.assertNotIn('COPY_REACHED',p.stdout)
                    if kind=='directory':entry.rmdir()
                    elif kind=='file':self.assertEqual(entry.read_text(),'preserve');entry.unlink()
                    else:self.assertTrue(entry.is_symlink());entry.unlink()
