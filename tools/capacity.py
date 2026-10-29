"""Formal daemon capacity/retention fixture, disposable Linux VM namespace."""
import datetime,hashlib,html,json,os,platform,socket,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pathquill.cli import call
from tools.supervision import run_group,unmount
FINAL=ROOT/'evidence/capacity.json'
def publish(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n');path.with_suffix('.html').write_text('<!doctype html><meta charset="utf-8"><pre>'+html.escape(json.dumps(value,indent=2))+'</pre>')
mode=sys.argv[1] if len(sys.argv)>1 else None
if mode!='worker' or len(sys.argv)!=4:
    publish(FINAL,dict(passed=False,status='orchestration_in_progress'))
if mode=='orchestrate' and len(sys.argv)==2:
    value=dict(passed=False,status='orchestration_failed')
    try:
        with tempfile.TemporaryDirectory(prefix='pq-report-') as reportdir:
            os.chown(reportdir,501,501);worker_report=Path(reportdir)/'worker.json'
            with tempfile.TemporaryDirectory(prefix='pq-cap-fs-') as mount:
                os.chmod(mount,0o755)
                subprocess.run(['mount','-t','tmpfs','-o','size=2m,mode=0777','tmpfs',mount],check=True)
                try:
                    code=run_group([sys.executable,__file__,'worker',mount,str(worker_report)],75)
                    value=json.loads(worker_report.read_text())
                    if code!=0 or not value['passed']:raise RuntimeError('worker failed')
                    required={'full_capture_seals_and_held_retention_survives_restart','reclaimed_capacity_reused_by_real_probe','real_tmpfs_ENOSPC_formal_daemon','rebuild_failure_does_not_starve_gc'}
                    if {x['name'] for x in value['cases']}!=required:raise RuntimeError('required case missing')
                finally:unmount(mount)
        value['orchestrator_cleanup']=True
    except Exception as error:value=dict(passed=False,error=type(error).__name__+': '+str(error))
    publish(FINAL,value);sys.exit(0 if value['passed'] else 1)
if mode!='worker' or len(sys.argv)!=4:
    raise SystemExit('Usage: capacity.py orchestrate (inside a disposable Linux VM)')
r=dict(passed=False,mvp_qualified=False,cases=[],environment=dict(system=platform.system(),release=platform.release(),python=platform.python_version(),utc=datetime.datetime.now(datetime.timezone.utc).isoformat()),limits=['Logical budgets, not filesystem quota or guaranteed writes on a physically full filesystem','Normal daemon process restart, not VM reboot or power loss','This runner exercises hold/release primitives; package publication is verified separately','Cross-boot reanchoring is unit-tested with altered metadata, not a real VM reboot'])
out=Path(sys.argv[3])
def save():
    out.write_text(json.dumps(r,indent=2)+'\n');out.with_suffix('.html').write_text('<!doctype html><meta charset="utf-8"><pre>'+html.escape(json.dumps(r,indent=2))+'</pre>')
def check(v,msg):
    if not v:raise RuntimeError(msg)
proc=None;server=None
try:
    if os.getuid()==0:
        subprocess.run(['ip','link','set','lo','up'],check=True);os.setgroups([]);os.setgid(501);os.setuid(501)
    save()
    import unittest
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),top_level_dir=str(ROOT));tests=unittest.TextTestRunner().run(suite);check(tests.wasSuccessful(),'tests failed');r['tests']=tests.testsRun
    with tempfile.TemporaryDirectory(prefix='pq-cap-') as tmp:
        tmp=Path(tmp);config=tmp/'config.json';probe=socket.socket();probe.bind(('127.0.0.1',0));port=probe.getsockname()[1];probe.close()
        config.write_text(json.dumps([dict(host='127.0.0.1',port=port,timeout=.1,interval=.2)]))
        root=tmp/'store';logpath=tmp/'daemon.log'
        def start():
            log=open(logpath,'ab');p=subprocess.Popen([sys.executable,'-m','pathquill.daemon','--root',str(root),'--config',str(config),'--data-bytes','4096','--slots','1','--retention-seconds','3'],cwd=ROOT,stdout=log,stderr=log);log.close();return p
        proc=start()
        def status():
            check(proc.poll() is None,'daemon exited: '+logpath.read_text());return call(root)
        def wait(predicate,timeout=12):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                try:
                    value=status()
                    if predicate(value):return value
                except (OSError,ValueError):pass
                time.sleep(.03)
            raise TimeoutError('capacity condition')
        from pathquill.core import boottime
        import sqlite3
        full=wait(lambda x:bool(x['incidents']) and x['capacity']['loss']>0)
        key=full['incidents'][0]['id'];epoch=full['epoch']
        check(call(root,'delete',epoch=epoch,id=key).get('error')=='capture_busy','active capture deleted')
        # Recover the target, keeping the listener drained for the real 30s window.
        server=socket.socket();server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);server.bind(('127.0.0.1',port));server.listen(128);server.settimeout(.1)
        import threading
        alive=True
        def accept():
            while alive:
                try:c,_=server.accept();c.close()
                except socket.timeout:pass
                except OSError:return
        thread=threading.Thread(target=accept,daemon=True);thread.start()
        sealed=wait(lambda x:any(i['id']==key and i['state']=='SEALED' for i in x['incidents']),40)
        check(next(i for i in sealed['incidents'] if i['id']==key)['coverage']=='PARTIAL','full capture falsely complete')
        raw=sqlite3.connect('file:'+str(root/'state.db')+'?mode=ro',uri=True)
        first,end=raw.execute('SELECT first,end FROM incidents WHERE id=?',(key,)).fetchone()
        progress=raw.execute('SELECT progress FROM control WHERE id=1').fetchone()[0];raw.close()
        check(end>=first+30 and boottime()>=end and progress>=end,'full seal lacked deadline barrier')
        held=call(root,'hold',id=key,epoch=epoch);token=next(h['token'] for h in held['capacity']['holds'] if h['id']==key)
        check(call(root,'delete',id=key,epoch=epoch).get('error')=='reference_busy','held capture deleted')
        # Stop/reopen without releasing the hold; retention may expire meanwhile.
        raw=sqlite3.connect('file:'+str(root/'state.db')+'?mode=ro',uri=True)
        anchor_before=raw.execute('SELECT boot,sealed,retention FROM lifetime WHERE id=?',(key,)).fetchone();raw.close()
        proc.kill();proc.wait(5);proc=start();restarted=wait(lambda x:x['epoch']!=epoch)
        raw=sqlite3.connect('file:'+str(root/'state.db')+'?mode=ro',uri=True)
        anchor_after=raw.execute('SELECT boot,sealed,retention FROM lifetime WHERE id=?',(key,)).fetchone();raw.close()
        check(anchor_before==anchor_after,'same boot restart changed retention anchor')
        check(any(h['token']==token for h in restarted['capacity']['holds']),'reference lost on restart')
        check(call(root,'release',id=key,token=token,epoch=epoch).get('error')=='stale_epoch','old release accepted')
        time.sleep(3.2);kept=call(root,'gc',epoch=restarted['epoch']);check(any(i['id']==key for i in kept['incidents']),'held expired capture collected')
        released=call(root,'release',id=key,token=token,epoch=restarted['epoch']);gone=call(root,'gc',epoch=restarted['epoch'])
        check(not any(i['id']==key for i in gone['incidents']),'expired unheld capture not collected')
        r['cases'].append(dict(name='full_capture_seals_and_held_retention_survives_restart',before=full['capacity'],sealed_coverage='PARTIAL',window_seconds=end-first,control_progress_after_deadline=progress-end,same_boot_anchor_preserved=True,after_gc=gone['capacity'],active_delete_rejected=True,held_delete_rejected=True,stale_release_rejected=True,passed=True))
        alive=False;thread.join(2);server.close();server=None
        # An expired slot is now available for a new real failure capture.
        admitted=wait(lambda x:any(i['state']=='CAPTURING' for i in x['incidents']))
        check(admitted['capacity']['incidents']==1,'slot not reusable')
        proc.terminate();check(proc.wait(6)==0,'graceful exit failed');check(not (root/'control.sock').exists(),'socket leaked')
        r['cases'].append(dict(name='reclaimed_capacity_reused_by_real_probe',passed=True))
    if len(sys.argv)>2:
        with tempfile.TemporaryDirectory(prefix='pq-disk-config-') as tmp:
            tmp=Path(tmp);config=tmp/'config.json';config.write_text('[]');root=Path(sys.argv[2])/'diskstore';logpath=tmp/'disk.log'
            def disk_start():
                log=open(logpath,'ab');p=subprocess.Popen([sys.executable,'-m','pathquill.daemon','--root',str(root),'--config',str(config)],cwd=ROOT,stdout=log,stderr=log);log.close();return p
            proc=disk_start()
            def status():
                check(proc.poll() is None,'storage daemon exited: '+logpath.read_text());return call(root)
            clean=wait(lambda x:x['committed']>0)
            filler=Path(sys.argv[2])/'filler'
            with open(filler,'wb',buffering=0) as f:
                try:
                    while True:f.write(b'x'*65536)
                except OSError as e:check(e.errno==28,'not ENOSPC')
            fault=wait(lambda x:x['capacity']['mode']=='STORAGE_ERROR')
            old_epoch=fault['epoch'];check(call(root,'gc',epoch=old_epoch).get('error')=='storage_degraded','fault admitted mutation')
            filler.unlink();time.sleep(.1);check(status()['capacity']['mode']=='STORAGE_ERROR','automatic unsafe repair')
            proc.terminate();check(proc.wait(6)==0,'fault shutdown failed');proc=disk_start()
            repaired=wait(lambda x:x['committed']>0 and x['capacity']['mode']=='OK')
            check(repaired['epoch']!=old_epoch,'no restart');check(call(root,'gc',epoch=old_epoch).get('error')=='stale_epoch','old GC accepted')
            cli=subprocess.run([sys.executable,'-m','pathquill.cli','--root',str(root),'--op','gc','--epoch',old_epoch],capture_output=True,text=True,timeout=5,cwd=ROOT)
            check(cli.returncode==1 and json.loads(cli.stdout)['error']=='stale_epoch','CLI reported refusal as success')
            proc.terminate();check(proc.wait(6)==0,'repaired shutdown failed')
            r['cases'].append(dict(name='real_tmpfs_ENOSPC_formal_daemon',mutation_refused=True,explicit_restart_repaired=True,stale_gc_rejected=True,passed=True))
    with tempfile.TemporaryDirectory(prefix='pq-gc-degraded-') as tmp:
        tmp=Path(tmp);root=tmp/'store';logpath=tmp/'gc.log'
        from pathquill.managed import ManagedRecorder
        seed=ManagedRecorder(root,retention=.1)
        expired=seed.incident({});seed.finish(expired,boottime()+31,seed.epoch,boottime()+31)
        protected=seed.incident({});seed.finish(protected,boottime()+31,seed.epoch,boottime()+31);seed.hold(protected,seed.epoch)
        seed.retention=100;unexpired=seed.incident({});seed.finish(unexpired,boottime()+31,seed.epoch,boottime()+31);seed.close();time.sleep(.2)
        bootstrap="""import sys
from unittest.mock import patch
from pathquill.managed import ManagedRecorder
from pathquill.state import State
from pathquill.daemon import serve
original=ManagedRecorder.__init__
def init(self,*args,**kwargs):
    original(self,*args,**kwargs);self.incident({})
def fail(self,backend):
    self.invalidate('injected_rebuild_failure');return False
with patch.object(ManagedRecorder,'__init__',init),patch.object(State,'rebuild',fail):
    serve(sys.argv[1],[])
"""
        log=open(logpath,'wb');proc=subprocess.Popen([sys.executable,'-c',bootstrap,str(root)],cwd=ROOT,stdout=log,stderr=log);log.close()
        def status():
            check(proc.poll() is None,'GC daemon exited: '+logpath.read_text());return call(root)
        first=wait(lambda x:x['state']=='DEGRADED' and any(i['state']=='CAPTURING' for i in x['incidents']))
        final=wait(lambda x:x['state']=='DEGRADED' and x['generation']>=4 and not any(i['id']==expired for i in x['incidents']))
        remaining={i['id'] for i in final['incidents']}
        check(protected in remaining and unexpired in remaining and any(i['state']=='CAPTURING' for i in final['incidents']),'GC removed protected data')
        proc.terminate();check(proc.wait(6)==0,'GC daemon shutdown failed')
        r['cases'].append(dict(name='rebuild_failure_does_not_starve_gc',injected_failure=True,generation=final['generation'],expired_collected=True,held_unexpired_active_preserved=True,passed=True))
    r['passed']=True
except Exception as e:r['error']=type(e).__name__+': '+str(e).replace(str(ROOT),'<checkout>')
finally:
    if server:server.close()
    if proc and proc.poll() is None:proc.kill();proc.wait(5)
    if os.getuid()==0:os.setgid(501);os.setuid(501)
    r['source']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*sorted((ROOT/'pathquill').glob('*.py')),*sorted((ROOT/'tests').glob('*.py')),ROOT/'tools/capacity.py',ROOT/'tools/supervision.py',ROOT/'pyproject.toml']};save()
sys.exit(0 if r['passed'] else 1)
