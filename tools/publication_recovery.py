"""Process-crash publication recovery through the formal daemon/CLI in Linux VM."""
import datetime,hashlib,html,json,os,platform,sqlite3,subprocess,sys,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pathquill.publication import PublicationRecorder
from tools.supervision import run_group
FINAL=ROOT/'evidence/publication-recovery.json'
def write(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n');path.with_suffix('.html').write_text('<!doctype html><meta charset="utf-8"><pre>'+html.escape(json.dumps(value,indent=2))+'</pre>')
def check(value,message):
    if not value:raise RuntimeError(message)
mode=sys.argv[1] if len(sys.argv)>1 else None
if mode=='orchestrate':
    write(FINAL,dict(passed=False,status='in_progress'))
    try:
        with tempfile.TemporaryDirectory(prefix='pq-reconcile-report-') as tmp:
            os.chown(tmp,501,501);out=Path(tmp)/'worker.json'
            code=run_group([sys.executable,__file__,'worker',str(out)],75);value=json.loads(out.read_text())
            required={'rename_completed_adopted_without_rewrite','cleanup_killed_after_unlink_resumes_without_early_release','unknown_stage_preserved','cancel_cleanup_survives_restart'}
            check(code==0 and value['passed'] and {case['name'] for case in value['cases']}==required,'incomplete verification')
        value['orchestrator_cleanup']=True
    except Exception as error:value=dict(passed=False,error=type(error).__name__)
    write(FINAL,value)
    if os.getuid()==0:os.chown(FINAL,501,501);os.chown(FINAL.with_suffix('.html'),501,501)
    sys.exit(0 if value['passed'] else 1)
if mode!='worker' or len(sys.argv)!=3:raise SystemExit('Usage: publication_recovery.py orchestrate in isolated Linux VM')
value=dict(passed=False,mvp_qualified=False,cases=[],environment=dict(system=platform.system(),release=platform.release(),python=platform.python_version(),utc=datetime.datetime.now(datetime.timezone.utc).isoformat()),limits=['Test-only wrapper pauses at formal rename/unlink boundaries, then parent sends actual SIGKILL; not an unmodified-launch timing experiment','Synthetic private source; no production incidents','Process restart only: no VM reboot, power loss or zero-gap boot qualification','Partial writes and fsync/SQLite failure are unit-injected, not physical disk failure','Private owned store; malicious same-UID mutation and published-artifact deletion/reader leases remain outside scope'])
children=[]
def wait(predicate,seconds=8):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:
            v=predicate()
            if v:return v
        except (OSError,ValueError,KeyError,subprocess.TimeoutExpired):pass
        time.sleep(.03)
    raise TimeoutError('recovery condition')
def stopped(p):
    check(p.poll() is None,'daemon exited before fault boundary')
    return '\nState:\tT' in Path('/proc/'+str(p.pid)+'/status').read_text()
def ledger(root):
    with sqlite3.connect('file:'+str(root/'state.db')+'?mode=ro',uri=True) as db:
        return db.execute('SELECT state,bytes,cleanup,outcome FROM publications WHERE request="work"').fetchone()
def fingerprints(directory):
    return {p.name:(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_ino,p.stat().st_mtime_ns) for p in directory.iterdir()}
try:
    if os.getuid()==0:
        subprocess.run(['ip','link','set','lo','up'],check=True);os.setgroups([]);os.setgid(501);os.setuid(501)
    tests=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover(str(ROOT/'tests'),top_level_dir=str(ROOT)))
    check(tests.wasSuccessful(),'tests failed');value['tests']=tests.testsRun
    with tempfile.TemporaryDirectory(prefix='pq-recovery-') as base:
        for case in ('adopt','cleanup','unknown','cancel'):
            tmp=Path(base)/case;tmp.mkdir();root=tmp/'store';config=tmp/'config.json';config.write_text('[]')
            seed=PublicationRecorder(root);source=seed.incident(dict(endpoints=['10.23.45.67','PRIVATE.example']),0);seed.finish(source,30,seed.epoch,30)
            seed.request_export('work',source,60,seed.epoch);seed.advance_exports();seed.advance_exports();seed.close()
            def start(fault=None):
                args=([str(ROOT/'tools/recovery_daemon.py'),fault] if fault else ['-m','pathquill.daemon'])
                with (tmp/'daemon.log').open('ab') as stream:p=subprocess.Popen([sys.executable,*args,'--root',str(root),'--config',str(config)],cwd=ROOT,stdout=stream,stderr=stream)
                children.append(p);return p
            def cli(op,epoch=None,ok=True):
                args=[sys.executable,'-m','pathquill.cli','--root',str(root),'--op',op,'--request','work']
                if epoch:args+=['--epoch',epoch]
                p=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=3);reply=json.loads(p.stdout)
                check((p.returncode==0)==ok and reply['ok']==ok,'CLI response/exit mismatch');return reply
            def alive(p):
                check(p.poll() is None,'formal daemon exited')
                return cli('status')
            p=start('after_rename' if case=='adopt' else 'before_rename');first=wait(lambda:alive(p));old=first['epoch']
            client=subprocess.Popen([sys.executable,'-m','pathquill.cli','--root',str(root),'--op','export-publish','--request','work','--epoch',old],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);children.append(client)
            wait(lambda:stopped(p));check(ledger(root)[0]=='PREPARING','not interrupted before completion record')
            p.kill();p.wait(3);client.communicate(timeout=3);check(client.returncode!=0,'killed publication falsely succeeded')
            names=list((root/'packages').iterdir());check(len(names)==1,'unexpected publication layout');artifact=names[0]
            if case=='adopt':
                before=fingerprints(artifact)
                for path in artifact.iterdir():
                    for raw in ('10.23.45.67','PRIVATE.example',source,str(root)):check(raw not in path.name+path.read_text(),'original leaked')
                begin=time.monotonic();p=start();current=wait(lambda:alive(p));ready_elapsed=time.monotonic()-begin;result=cli('publication-status')['export']
                check(result['state']=='PUBLISHED' and fingerprints(artifact)==before,'recovery rewrote published files')
                check(cli('export-cancel',current['epoch'],False)['error']=='already_published','cancel deleted final')
                check(cli('publication-reconcile',old,False)['error']=='stale_epoch','old epoch accepted')
                value['cases'].append(dict(name='rename_completed_adopted_without_rewrite',restart_ready_seconds=ready_elapsed,files_unchanged=True,passed=True))
            elif case=='cleanup':
                reserved=ledger(root)[1];p=start('cleanup_unlink');wait(lambda:stopped(p))
                record=ledger(root);check(record[0]=='CLEANUP_PENDING' and record[1]==reserved and len(list(artifact.iterdir()))==2,'cleanup freed reservation early')
                p.kill();p.wait(3);p=start();current=wait(lambda:alive(p))
                wait(lambda:cli('publication-status')['export']['state']=='CLEANED')
                check(not artifact.exists() and ledger(root)[1]==0,'cleanup not durably completed')
                check(cli('export-status')['export']['state']=='INTERRUPTED','old work resumed')
                check(cli('export-publish',current['epoch'],False)['error']=='publication_requires_reconciliation','old publication replayed')
                value['cases'].append(dict(name='cleanup_killed_after_unlink_resumes_without_early_release',reserved_bytes_while_incomplete=reserved,remaining_files_at_second_kill=2,passed=True))
            elif case=='unknown':
                (artifact/'unknown').write_text('operator-data');before=fingerprints(artifact);reserved=ledger(root)[1]
                p=start();current=wait(lambda:alive(p));check(cli('publication-status')['export']['state']=='BLOCKED','unknown data accepted')
                check(cli('publication-reconcile',current['epoch'])['export']['state']=='BLOCKED','unknown data unblocked')
                check(cli('export-cancel',current['epoch'],False)['error']=='publication_requires_reconciliation','unknown cancellation deleted data')
                check(fingerprints(artifact)==before and ledger(root)[1]==reserved,'unknown files/credit changed')
                value['cases'].append(dict(name='unknown_stage_preserved',files_preserved=len(before),passed=True))
            else:
                p=start();current=wait(lambda:alive(p));cancelled=cli('export-cancel',current['epoch'])['export'];check(cancelled['state']=='CLEANUP_PENDING' and cancelled['outcome']=='CANCELLED','cancel not persisted')
                check(ledger(root)[3]=='CANCELLED' and ledger(root)[1]>0,'cancel freed credit early')
                p.kill();p.wait(3);p=start();wait(lambda:alive(p));wait(lambda:cli('publication-status')['export']['state']=='CLEANED')
                check(cli('export-status')['export']['state']=='CANCELLED' and not artifact.exists(),'cancel lost across restart')
                value['cases'].append(dict(name='cancel_cleanup_survives_restart',passed=True))
            p.terminate();check(p.wait(6)==0,'shutdown failed');check(not (root/'control.sock').exists(),'control socket leaked')
    value['passed']=True
except Exception as error:value['error']=type(error).__name__+': '+str(error).replace(str(ROOT),'<checkout>')
finally:
    for p in children:
        if p.poll() is None:p.kill()
        p.wait(5)
    value['source']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*sorted((ROOT/'pathquill').glob('*.py')),*sorted((ROOT/'tests').glob('*.py')),ROOT/'tools/publication_recovery.py',ROOT/'tools/recovery_daemon.py',ROOT/'tools/supervision.py',ROOT/'pyproject.toml']}
    write(Path(sys.argv[2]),value)
sys.exit(0 if value['passed'] else 1)
