"""Root orchestrator in disposable VM namespace; product work drops privileges."""
import hashlib,html,json,os,socket,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pathquill.recorder import Recorder
from pathquill.netlink import RouteSocket
from pathquill.core import boottime,Refused

def check(v,msg):
    if not v:raise RuntimeError(msg)
def report(out,r):
    out=Path(out);out.write_text(json.dumps(r,indent=2)+'\n');out.with_suffix('.html').write_text('<!doctype html><meta charset="utf-8"><pre>'+html.escape(json.dumps(r,indent=2))+'</pre>')

if sys.argv[1]=='worker':
    os.setgroups([]);os.setgid(501);os.setuid(501)
    r=dict(passed=False,mvp_qualified=False,source={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(list((ROOT/'pathquill').glob('*.py'))+list((ROOT/'tests').glob('*.py'))+[ROOT/'tools/continued.py'])},cases=[],limits=['No power loss, suspend, real kernel ENOBUFS or long-term stability qualification','Dump data and interleaved notifications are interval evidence, not an atomic current-state reconstruction','No automatic retention, full daemon/systemd or bounded export-file publication yet'])
    try:
        suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),top_level_dir=str(ROOT));result=unittest.TextTestRunner(verbosity=2).run(suite);check(result.wasSuccessful(),'tests failed');r['tests']=result.testsRun
        nl=RouteSocket()
        try:
            subprocess.run(['sudo','ip','link','set','pq1','up'],check=True)
            snap=nl.synchronize();check(snap['valid'] and len(snap['dumps'])==3,'dumps failed');check(any(x['kind']==16 for x in snap['notifications']),'notification missing')
            r['cases'].append(dict(name='subscribed_dump_and_notification',dumps=snap['dumps'],notification_count=len(snap['notifications']),passed=True))
        finally:nl.close()
        with tempfile.TemporaryDirectory() as tmp:
            s=Recorder(tmp);s.observe(dict(kind='pre_observation'));server=socket.socket();server.bind(('127.0.0.1',0));server.listen();port=server.getsockname()[1]
            check(s.probe('127.0.0.1',port)=='success','real TCP success failed');server.close()
            check(s.probe('127.0.0.1',port)=='refused','real refused failed')
            s.observe(dict(kind='after_trigger'))
            check(s.db.execute('SELECT count(*) FROM incidents').fetchone()[0]==1,'no triggered capture');check(s.db.execute('SELECT count(*) FROM capture').fetchone()[0]>=3,'missing persisted prebuffer')
            udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);udp.bind(('127.0.0.1',0))
            def answer():
                data,peer=udp.recvfrom(4096);udp.sendto(data[:2]+b'\x81\x82'+data[4:],peer)
            thread=threading.Thread(target=answer);thread.start();check(s.dns('127.0.0.1',udp.getsockname()[1])=='dns_error','DNS failure not recognized');thread.join(2);udp.close()
            r['cases'].append(dict(name='real_TCP_DNS_trigger_with_persistent_prebuffer',observations=s.db.execute('SELECT count(*) FROM capture').fetchone()[0],passed=True));s.close()
        for mode in ('full','readonly'):
            path=Path(sys.argv[3])/mode
            s=Recorder(path)
            if mode=='full':
                fill=path/'filler'
                with open(fill,'wb',buffering=0) as f:
                    try:
                        while True:f.write(b'x'*65536)
                    except OSError as e:check(e.errno==28,'not ENOSPC')
            else:
                s.close()
                subprocess.run(['sudo','mount','-o','remount,ro',str(path)],check=True)
                try:Recorder(path)
                except (OSError,__import__('sqlite3').Error):pass
                else:raise RuntimeError('readonly startup accepted')
                subprocess.run(['sudo','mount','-o','remount,rw',str(path)],check=True)
                s=Recorder(path);s.observe(dict(kind='repaired'));s.close()
                r['cases'].append(dict(name='filesystem_readonly_startup_refusal',repair_reopen=True,passed=True));continue
            failed=False
            try:s.observe(dict(kind='fault'))
            except Exception:failed=True
            check(failed and s.degraded,mode+' did not fail closed')
            try:s.incident({})
            except Refused:pass
            else:raise RuntimeError('admitted while degraded')
            s.close()
            if mode=='full':fill.unlink()
            else:subprocess.run(['sudo','mount','-o','remount,rw',str(path)],check=True)
            s=Recorder(path);s.observe(dict(kind='repaired'));s.close()
            r['cases'].append(dict(name='filesystem_'+mode,repair_reopen=True,passed=True))
        r['passed']=True
    except Exception as e:r['error']=type(e).__name__+': '+str(e).replace(str(ROOT),'<checkout>')
    report(sys.argv[2],r);sys.exit(0 if r['passed'] else 1)
else:
    report(sys.argv[2],dict(passed=False,status='orchestration_in_progress'))
    os.chown(sys.argv[2],501,501);os.chown(str(Path(sys.argv[2]).with_suffix('.html')),501,501)
    with tempfile.TemporaryDirectory(prefix='pq-fs-') as tmp:
        paths=[];os.chmod(tmp,0o755)
        try:
            for mode in ('full','readonly'):
                p=Path(tmp)/mode;p.mkdir();subprocess.run(['mount','-t','tmpfs','-o','size=2m,mode=0777','tmpfs',str(p)],check=True);paths.append(p)
            subprocess.run(['ip','link','set','lo','up'],check=True)
            subprocess.run(['ip','link','add','pq1','type','dummy'],check=True)
            result=subprocess.run([sys.executable,__file__,'worker',sys.argv[2],tmp],timeout=60)
        finally:
            for p in reversed(paths):
                cleanup=subprocess.run(['umount',str(p)])
                if cleanup.returncode:
                    report(sys.argv[2],dict(passed=False,error='mount_cleanup_failed'));raise RuntimeError('cleanup failed')
    sys.exit(result.returncode)
