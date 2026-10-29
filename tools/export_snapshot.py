"""Synthetic sensitive source events, actual daemon request/GC/restart behavior."""
import datetime,hashlib,html,json,os,subprocess,sys,tempfile,time,unittest,threading,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pathquill.exports import ExportRecorder
from pathquill.cli import call
from tools.supervision import run_group
FINAL=ROOT/'evidence/export-snapshot.json'
def publish(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n');path.with_suffix('.html').write_text('<!doctype html><meta charset="utf-8"><pre>'+html.escape(json.dumps(value,indent=2))+'</pre>')
    if os.getuid()==0:os.chown(path,501,501);os.chown(path.with_suffix('.html'),501,501)
mode=sys.argv[1] if len(sys.argv)>1 else None
if mode!='worker' or len(sys.argv)!=3:publish(FINAL,dict(passed=False,status='in_progress'))
if mode=='orchestrate' and len(sys.argv)==2:
    value=dict(passed=False)
    try:
        with tempfile.TemporaryDirectory(prefix='pq-export-report-') as tmp:
            os.chown(tmp,501,501);report=Path(tmp)/'report.json'
            code=run_group([sys.executable,__file__,'worker',str(report)],30)
            value=json.loads(report.read_text())
            required={'dedup_cancel_and_new_owner_protection','fixed_redacted_snapshot_survives_source_gc','restart_interrupts_pending_preserves_ready_and_other_owner'}
            if code or not value['passed'] or {x['name'] for x in value['cases']}!=required:raise RuntimeError('incomplete export verification')
        value['orchestrator_cleanup']=True
    except Exception as error:value=dict(passed=False,error=type(error).__name__+': '+str(error))
    publish(FINAL,value);sys.exit(0 if value['passed'] else 1)
if mode!='worker' or len(sys.argv)!=3:raise SystemExit('Usage: export_snapshot.py orchestrate inside isolated Linux VM')
r=dict(passed=False,mvp_qualified=False,cases=[],environment=dict(system='Linux VM',utc=datetime.datetime.now(datetime.timezone.utc).isoformat()),limits=['Sources are synthetic privacy fixtures seeded through product API, not real network incidents','Process SIGKILL/restart only; no VM reboot or power loss','This runner exercises SQLite snapshots only; package publication is verified separately','Unknown ownership is fail-closed BLOCKED; operator repair interface remains deferred'])
proc=None
out=Path(sys.argv[2])
def save():
    out.write_text(json.dumps(r,indent=2)+'\n');out.with_suffix('.html').write_text('<!doctype html><meta charset="utf-8"><pre>'+html.escape(json.dumps(r,indent=2))+'</pre>')
def check(v,message):
    if not v:raise RuntimeError(message)
try:
    if os.getuid()==0:
        subprocess.run(['ip','link','set','lo','up'],check=True);os.setgroups([]);os.setgid(501);os.setuid(501)
    save();suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),top_level_dir=str(ROOT));tests=unittest.TextTestRunner().run(suite);check(tests.wasSuccessful(),'tests failed');r['tests']=tests.testsRun
    with tempfile.TemporaryDirectory(prefix='pq-export-') as tmp:
        tmp=Path(tmp);root=tmp/'store';seed=ExportRecorder(root);keys=[]
        for i in range(3):
            base=i*100
            seed.observe(dict(kind='state_object',group='links',value=dict(index=7,attributes={'3':b'PRIVATE-NIC\0'.hex(),'1':'aabbccddeeff'})),base)
            seed.observe(dict(kind='state_object',group='addresses',value=dict(index=7,family=2,prefix=24,attributes={'1':'0a172d43'})),base+1)
            seed.observe(dict(kind='state_object',group='routes',value=dict(family=2,dst_prefix=24,attributes={'1':'0a172d00','5':'0a172d43','4':'07000000'})),base+1.5)
            seed.observe(dict(kind='tcp',outcome='refused',free_text='<script>PRIVATE-ERROR</script>'),base+2)
            key=seed.incident(dict(endpoints=['10.23.45.67','Private.Example.','private.example','AA:BB:CC:DD:EE:FF']),base+3)
            seed.retention=.1 if i==1 else 86400;seed.finish(key,base+33,seed.epoch,base+33);keys.append(key)
        seed.close();config=tmp/'config.json';config.write_text('[]');logpath=tmp/'daemon.log'
        def start():
            log=open(logpath,'ab');p=subprocess.Popen([sys.executable,'-m','pathquill.daemon','--root',str(root),'--config',str(config)],cwd=ROOT,stdout=log,stderr=log);log.close();return p
        proc=start()
        def status():
            check(proc.poll() is None,'daemon exited: '+logpath.read_text());return call(root)
        def wait(predicate,timeout=8):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                try:
                    value=status()
                    if predicate(value):return value
                except (OSError,ValueError):pass
                time.sleep(.01)
            raise TimeoutError('export condition')
        first=wait(lambda v:v['state']=='RECORDING');epoch=first['epoch']
        check(call(root,'export',epoch=epoch,id=keys[0],request='huge',seconds=10**400).get('error')=='deadline','huge deadline not rejected')
        check(status()['epoch']==epoch,'huge deadline stopped daemon')
        submitted=call(root,'export',epoch=epoch,id=keys[0],request='cancel_me',seconds=30)
        check(submitted['export']['state']=='QUEUED','not admitted')
        duplicate=call(root,'export',epoch=epoch,id=keys[0],request='cancel_me',seconds=30)
        check(duplicate['export']['deadline']==submitted['export']['deadline'],'dedup extended deadline')
        check(call(root,'export',epoch=epoch,id=keys[0],request='cancel_me',seconds=20)['error']=='request_conflict','conflict accepted')
        check(call(root,'delete',epoch=epoch,id=keys[0])['error']=='reference_busy','source unprotected')
        cancelled=call(root,'export-cancel',epoch=epoch,request='cancel_me');check(cancelled['export']['state']=='CANCELLED','cancel failed')
        manual=call(root,'hold',epoch=epoch,id=keys[0]);token=next(h['token'] for h in manual['capacity']['holds'] if h['id']==keys[0])
        call(root,'export-cancel',epoch=epoch,request='cancel_me')
        check(any(h['token']==token for h in status()['capacity']['holds']),'old cancel released new owner')
        r['cases'].append(dict(name='dedup_cancel_and_new_owner_protection',passed=True))
        call(root,'export',epoch=epoch,id=keys[1],request='ready',seconds=30)
        protected=call(root,'gc',epoch=epoch);check(any(i['id']==keys[1] for i in protected['incidents']),'GC deleted source before snapshot')
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            if call(root,'export-status',request='ready')['export']['state']=='SNAPSHOT_READY':break
            time.sleep(.05)
        else:raise TimeoutError('no snapshot')
        snapshot=call(root,'export-read',request='ready')
        text=json.dumps(snapshot)
        for raw in ['10.23.45.67','PRIVATE-NIC','Private.Example','private.example','aabbccddeeff','0a172d43','PRIVATE-ERROR','<script>']:check(raw not in text,'sensitive fixture leaked')
        groups={x['group']:x['state'] for x in snapshot['export']['snapshot']['observations'] if x['kind']=='state_object'}
        check(set(groups)=={'links','addresses','routes'},'redaction dropped state groups')
        endpoints=snapshot['export']['snapshot']['incident']['endpoints']
        check(groups['links']['interface']==groups['addresses']['interface']==groups['routes']['interface'],'interface aliases lost association')
        check(groups['addresses']['address']==groups['routes']['gateway']==endpoints[0],'IP aliases lost association')
        check(groups['routes']['destination']!=groups['routes']['gateway'] and groups['links']['mac']==endpoints[3],'distinct address or MAC relationship lost')
        check(set(snapshot)=={'ok','export'},'raw daemon status mixed with snapshot')
        call(root,'gc',epoch=epoch);check(not any(i['id']==keys[1] for i in status()['incidents']),'source not reclaimed after snapshot')
        check(call(root,'export-read',request='ready')==snapshot,'snapshot changed after GC')
        from pathquill.core import boottime
        stop_reads=threading.Event();errors=[];counts=[0]*6
        def read_loop(index):
            try:
                while not stop_reads.is_set():
                    check(call(root,'export-read',request='ready')==snapshot,'polling snapshot changed');counts[index]+=1
            except Exception as error:errors.append(type(error).__name__);stop_reads.set()
        readers=[threading.Thread(target=read_loop,args=(i,),daemon=True) for i in range(6)]
        begin=boottime()
        for reader in readers:reader.start()
        try:
            time.sleep(1.2)
            raw=sqlite3.connect('file:'+str(root/'state.db')+'?mode=ro',uri=True)
            progress=raw.execute('SELECT progress FROM control').fetchone()[0];raw.close()
            check(progress>=begin+.5,'snapshot reads starved writer progress')
        finally:
            stop_reads.set()
            for reader in readers:reader.join(3)
        check(not errors and sum(counts)>10 and not any(reader.is_alive() for reader in readers),'snapshot read polling failed')
        r['cases'].append(dict(name='fixed_redacted_snapshot_survives_source_gc',observations=len(snapshot['export']['snapshot']['observations']),snapshot_digest=snapshot['export']['digest'],raw_values_absent=True,state_alias_relationships_preserved=True,concurrent_reads=sum(counts),progress_during_reads=progress-begin,passed=True))
        call(root,'export',epoch=epoch,id=keys[2],request='restart',seconds=30)
        proc.kill();proc.wait(5);proc=start();current=wait(lambda v:v['epoch']!=epoch)
        check(call(root,'export-status',request='restart')['export']['state']=='INTERRUPTED','pending job revived')
        check(call(root,'export-cancel',epoch=epoch,request='restart')['error']=='stale_epoch','old cancel accepted')
        check(call(root,'export-read',request='ready')==snapshot,'ready snapshot changed across restart')
        check(any(h['token']==token for h in current['capacity']['holds']),'manual hold released at recovery')
        check(not any(h['id']==keys[2] for h in current['capacity']['holds']),'interrupted job leaked own hold')
        r['cases'].append(dict(name='restart_interrupts_pending_preserves_ready_and_other_owner',passed=True))
        proc.terminate();check(proc.wait(6)==0,'shutdown failed');check(not (root/'control.sock').exists(),'socket leaked')
    r['passed']=True
except Exception as error:r['error']=type(error).__name__+': '+str(error).replace(str(ROOT),'<checkout>')
finally:
    if proc and proc.poll() is None:proc.kill();proc.wait(5)
    if os.getuid()==0:os.setgid(501);os.setuid(501)
    r['source']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*sorted((ROOT/'pathquill').glob('*.py')),*sorted((ROOT/'tests').glob('*.py')),ROOT/'tools/export_snapshot.py',ROOT/'tools/supervision.py',ROOT/'pyproject.toml']};save()
sys.exit(0 if r['passed'] else 1)
