"""Explicit retirement and full-history archive workflow, actual daemon/CLI."""
import datetime,hashlib,html,json,os,platform,sqlite3,subprocess,sys,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pathquill.publication import PublicationRecorder
from tools.supervision import run_group
FINAL=ROOT/'evidence/retention.json'
def write(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n');path.with_suffix('.html').write_text('<!doctype html><meta charset="utf-8"><pre>'+html.escape(json.dumps(value,indent=2))+'</pre>')
def check(value,message):
    if not value:raise RuntimeError(message)
mode=sys.argv[1] if len(sys.argv)>1 else None
if mode=='orchestrate':
    write(FINAL,dict(passed=False,status='in_progress'))
    try:
        with tempfile.TemporaryDirectory(prefix='pq-retention-report-') as tmp:
            os.chown(tmp,501,501);out=Path(tmp)/'worker.json'
            code=run_group([sys.executable,__file__,'worker',str(out)],75);value=json.loads(out.read_text())
            required={'seal_commit_crash_archive_recovery_without_reopening','retirement_unlink_crash_keeps_credit_then_recovers','unknown_published_data_preserved','full_history_seal_archive_new_store_and_stale_rejection'}
            check(code==0 and value['passed'] and {c['name'] for c in value['cases']}==required,'incomplete verification')
        value['orchestrator_cleanup']=True
    except Exception as error:value=dict(passed=False,error=type(error).__name__)
    write(FINAL,value)
    if os.getuid()==0:os.chown(FINAL,501,501);os.chown(FINAL.with_suffix('.html'),501,501)
    sys.exit(0 if value['passed'] else 1)
if mode!='worker' or len(sys.argv)!=3:raise SystemExit('Usage: retention.py orchestrate in isolated Linux VM')
value=dict(passed=False,mvp_qualified=False,cases=[],environment=dict(system=platform.system(),release=platform.release(),python=platform.python_version(),utc=datetime.datetime.now(datetime.timezone.utc).isoformat()),limits=['Synthetic source seeded through product API; actual formal daemon and subprocess CLI','Crash cases use test-only pauses after production unlink/seal commit followed by actual SIGKILL','Process restarts only; no VM reboot, power loss or physical media failure','Archive is an in-place sealed private store plus integrity receipt, not an independent backup or tamper-proof storage','No automatic rollover, unseal, external-reader lease or automated retention; copy artifacts before explicit retirement','Interrupted partial archive receipts/new-store initialization fail closed; no automated repair promised'])
children=[]
def wait(predicate,seconds=8):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:
            result=predicate()
            if result:return result
        except (OSError,ValueError,KeyError):pass
        time.sleep(.03)
    raise TimeoutError('retention condition')
def query(root,sql):
    with sqlite3.connect((root/'state.db').as_uri()+'?mode=ro',uri=True) as db:return db.execute(sql).fetchone()
def fingerprints(directory):return {p.name:(p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns) for p in directory.iterdir()}
def cli(root,op,ok=True,**fields):
    args=[sys.executable,'-m','pathquill.cli','--root',str(root),'--op',op]
    for name,data in fields.items():args+=['--'+name,str(data)]
    p=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=6);reply=json.loads(p.stdout)
    check((p.returncode==0)==ok and reply['ok']==ok,'CLI exit/reply mismatch');return reply
try:
    if os.getuid()==0:
        subprocess.run(['ip','link','set','lo','up'],check=True);os.setgroups([]);os.setgid(501);os.setuid(501)
    tests=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover(str(ROOT/'tests'),top_level_dir=str(ROOT)))
    check(tests.wasSuccessful(),'tests failed');value['tests']=tests.testsRun
    with tempfile.TemporaryDirectory(prefix='pq-retention-') as base:
        base=Path(base);config=base/'config.json';config.write_text('[]')
        def seed(root,publish=False):
            r=PublicationRecorder(root);key=r.incident(dict(endpoints=['10.23.45.67']),0);r.finish(key,30,r.epoch,30);result=None
            if publish:
                r.request_export('work',key,60,r.epoch);r.advance_exports();r.advance_exports();result=r.publish_export('work',r.epoch)
            r.close();return key,result
        def start(root,fault=None):
            args=[str(ROOT/'tools/recovery_daemon.py'),fault] if fault else ['-m','pathquill.daemon']
            with (base/'daemon.log').open('ab') as log:p=subprocess.Popen([sys.executable,*args,'--root',str(root),'--config',str(config)],cwd=ROOT,stdout=log,stderr=log)
            children.append(p);return p
        def ready(root,p):
            check(p.poll() is None,'daemon exited');return cli(root,'status')
        root=base/'retire';source,published=seed(root,True);p=start(root,'retire_unlink');status=wait(lambda:ready(root,p));epoch=status['epoch'];store=status['store_id'];package=published['package'];final=root/'packages'/package
        check(cli(root,'publication-retire',False,request='work',package=package,epoch=epoch,store='wrong')['error']=='store_mismatch','wrong store retired')
        reply=cli(root,'publication-retire',request='work',package=package,epoch=epoch,store=store)
        check(reply['export']['state']=='RETIRE_PENDING','retirement not accepted')
        wait(lambda:'\nState:\tT' in Path('/proc/'+str(p.pid)+'/status').read_text())
        record=query(root,"SELECT state,bytes FROM publications WHERE request='work'")
        check(record==('RETIRE_PENDING',published['bytes']) and len(list(final.iterdir()))==2,'credit freed before retirement completion')
        p.kill();p.wait(3);p=start(root);current=wait(lambda:ready(root,p))
        wait(lambda:cli(root,'publication-status',request='work')['export']['state']=='CLEANED')
        check(not final.exists() and query(root,"SELECT bytes FROM publications WHERE request='work'")[0]==0,'retirement cleanup incomplete')
        check(cli(root,'export-status',request='work')['export']['state']=='RETIRED','retirement outcome lost')
        check(cli(root,'publication-retire',False,request='work',package=package,epoch=epoch,store=store)['error']=='stale_epoch','old retirement accepted')
        check(cli(root,'export',request='work',id=source,seconds=60,epoch=current['epoch'],store=store)['export']['state']=='RETIRED','old request replayed')
        p.terminate();check(p.wait(6)==0,'shutdown failed')
        value['cases'].append(dict(name='retirement_unlink_crash_keeps_credit_then_recovers',reserved_bytes_while_incomplete=published['bytes'],remaining_files_at_kill=2,passed=True))
        root=base/'unknown';source,published=seed(root,True);final=root/'packages'/published['package'];(final/'unknown').write_text('operator-data');before=fingerprints(final)
        p=start(root);status=wait(lambda:ready(root,p))
        check(cli(root,'publication-retire',False,request='work',package=published['package'],epoch=status['epoch'],store=status['store_id'])['error']=='publication_not_published','unknown files retired')
        check(fingerprints(final)==before and query(root,"SELECT bytes FROM publications WHERE request='work'")[0]==published['bytes'],'unknown data or credit changed')
        p.terminate();check(p.wait(6)==0,'shutdown failed');value['cases'].append(dict(name='unknown_published_data_preserved',files_preserved=4,passed=True))
        root=base/'seal_crash';source,_=seed(root);p=start(root,'seal_commit');status=wait(lambda:ready(root,p))
        args=[sys.executable,'-m','pathquill.cli','--root',str(root),'--op','store-seal','--store',status['store_id'],'--epoch',status['epoch']]
        client=subprocess.Popen(args,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);children.append(client)
        wait(lambda:'\nState:\tT' in Path('/proc/'+str(p.pid)+'/status').read_text())
        check(query(root,"SELECT value FROM meta WHERE key='lifecycle'")[0]=='SEALED' and not (root/'control.sock').exists(),'seal crash not durably fenced')
        p.kill();p.wait(3);client.communicate(timeout=3);check(client.returncode!=0,'lost seal response falsely succeeded')
        check(cli(root,'store-archive',store=status['store_id'])['archive']['store_id']==status['store_id'],'sealed crash cannot archive')
        value['cases'].append(dict(name='seal_commit_crash_archive_recovery_without_reopening',passed=True))
        root=base/'full';source,_=seed(root);p=start(root);status=wait(lambda:ready(root,p));epoch=status['epoch'];identity=status['store_id']
        for i in range(32):
            request='old_'+str(i);cli(root,'export',request=request,id=source,seconds=60,epoch=epoch,store=identity);cli(root,'export-cancel',request=request,epoch=epoch,store=identity)
        check(cli(root,'export',False,request='overflow',id=source,seconds=60,epoch=epoch,store=identity)['error']=='export_history_full','33rd history admitted')
        capacity=cli(root,'status')['capacity']['export_history'];check(capacity==dict(used=32,limit=32,remaining=0),'history usage incorrect')
        check(cli(root,'store-archive',False,store=identity)['error']=='writer_busy','live store archived')
        sealed=cli(root,'store-seal',epoch=epoch,store=identity);check(sealed['lifecycle']=='SEALED','seal not durable');check(p.wait(6)==0,'sealed daemon did not stop')
        before=hashlib.sha256((root/'state.db').read_bytes()).hexdigest();p=start(root);check(p.wait(5)!=0,'sealed store restarted')
        check(hashlib.sha256((root/'state.db').read_bytes()).hexdigest()==before,'sealed startup changed DB')
        archive=cli(root,'store-archive',store=identity)['archive'];check(archive['history_used']==32,'archive lost history')
        check(cli(root,'store-archive',store=identity)['archive']==archive,'archive not idempotent')
        fresh=base/'fresh';created=cli(fresh,'store-new',archive=root,store=identity)['archive'];check(created['store_id']!=identity,'store identity reused')
        check(cli(fresh,'store-new',False,archive=root,store=identity)['error']=='new_store_exists','existing new store overwritten')
        new_source,_=seed(fresh);p=start(fresh);current=wait(lambda:ready(fresh,p));check(current['capacity']['export_history']['remaining']==32,'new history not fresh')
        check(cli(fresh,'export',False,request='old_0',id=source,seconds=60,epoch=current['epoch'],store=identity)['error']=='store_mismatch','old store request replayed')
        check(cli(fresh,'export',False,request='old_0',id=source,seconds=60,epoch=epoch,store=current['store_id'])['error']=='stale_epoch','old epoch replayed')
        check(cli(fresh,'export',False,request='old_0',id=source,seconds=60,epoch=current['epoch'],store=current['store_id'])['error']=='not_sealed','old source copied to new store')
        cli(fresh,'export',request='new_0',id=new_source,seconds=60,epoch=current['epoch'],store=current['store_id']);cli(fresh,'export-cancel',request='new_0',epoch=current['epoch'],store=current['store_id'])
        check(query(root,'SELECT count(*) FROM exports')[0]==32 and hashlib.sha256((root/'state.db').read_bytes()).hexdigest()==before,'old archive changed')
        p.terminate();check(p.wait(6)==0,'fresh shutdown failed')
        value['cases'].append(dict(name='full_history_seal_archive_new_store_and_stale_rejection',history_used=32,new_store_initial_remaining=32,old_database_unchanged=True,passed=True))
    value['passed']=True
except Exception as error:value['error']=type(error).__name__+': '+str(error).replace(str(ROOT),'<checkout>')
finally:
    for p in children:
        if p.poll() is None:p.kill()
        p.wait(5)
    value['source']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*sorted((ROOT/'pathquill').glob('*.py')),*sorted((ROOT/'tests').glob('*.py')),ROOT/'tools/retention.py',ROOT/'tools/recovery_daemon.py',ROOT/'tools/supervision.py',ROOT/'pyproject.toml']}
    write(Path(sys.argv[2]),value)
sys.exit(0 if value['passed'] else 1)
