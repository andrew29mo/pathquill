"""Run inside a disposable Linux network namespace. No host networking changes."""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pathquill.core import Store,Observer,boottime
from pathquill.netlink import RouteSocket

p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--uid',type=int,required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[1]
r=dict(passed=False,mvp_qualified=False,platform='Linux VM / isolated network namespace',cases=[],source={str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(list((root/'pathquill').glob('*.py'))+list((root/'tests').glob('*.py'))+[root/'tools/explore.py'])},limits=['No VM reboot, power loss or suspend test','No actual kernel ENOBUFS generation; loss behavior is injected','No persistent prebuffer, full snapshot reconciliation, real DNS probes or automatic capture daemon yet','No physical disk-full or read-only filesystem test; SQLite FULL is real, query_only is connection-level fault injection'])
def check(v,message):
    if not v:raise RuntimeError(message)
try:
    subprocess.run(['ip','link','add','pq0','type','dummy'],check=True)
    os.setgroups([]);os.setgid(a.uid);os.setuid(a.uid)
    suite=unittest.defaultTestLoader.discover(str(root/'tests'),top_level_dir=str(root))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    check(result.wasSuccessful(),'core tests failed');r['tests']=dict(count=result.testsRun,failures=len(result.failures),errors=len(result.errors))
    listener=RouteSocket()
    try:
        subprocess.run(['sudo','ip','link','set','pq0','up'],check=True)
        messages=listener.receive();check(any(x['kind']==16 for x in messages),'No real link notification')
        r['cases'].append(dict(name='unprivileged_real_netlink',uid=os.getuid(),message_types=[x['kind'] for x in messages],passed=True))
    finally:listener.close()
    start=boottime();time.sleep(.08);elapsed=boottime()-start;check(.07<elapsed<2,'clock observation failed')
    r['cases'].append(dict(name='boottime_elapsed',seconds=elapsed,passed=True))
    with tempfile.TemporaryDirectory(prefix='pq-crash-') as tmp:
        code='from pathquill.core import Store;import sys,time;s=Store(sys.argv[1]);k=s.trigger(0,{"endpoints":["secret.example"]});print(k,flush=True);time.sleep(60)'
        child=subprocess.Popen([sys.executable,'-c',code,tmp],cwd=root,stdout=subprocess.PIPE,text=True)
        key=child.stdout.readline().strip();check(bool(key),'child not committed');child.kill();child.wait(3)
        s=Store(tmp)
        try:
            row=s.db.execute('SELECT state,coverage,reason FROM incidents WHERE id=?',(key,)).fetchone()
            check(row==('SEALED','PARTIAL','restart'),'crash recovery failed')
            out=s.export(key);check('secret' not in out['json'] and 'secret' not in out['html'],'identifier leaked')
            s.db.execute('PRAGMA query_only=ON')
            try:s.trigger(100,{})
            except Exception:pass
            else:raise RuntimeError('readonly accepted write')
            check(s.degraded,'readonly did not degrade')
            r['cases'].append(dict(name='SIGKILL_committed_capture',child_exit=child.returncode,recovered=list(row),redacted=True,passed=True))
        finally:s.close()
    r['passed']=True
except Exception as exc:r['error']=type(exc).__name__+': '+str(exc).replace(str(root),'<checkout>')
finally:
    if os.getuid()==0:os.setgid(a.uid);os.setuid(a.uid)
    out=Path(a.output);out.write_text(json.dumps(r,indent=2)+'\n');out.with_suffix('.html').write_text('<!doctype html><meta charset="utf-8"><h1>Pathquill exploration</h1><pre>'+html.escape(json.dumps(r,indent=2))+'</pre>')
sys.exit(0 if r['passed'] else 1)
