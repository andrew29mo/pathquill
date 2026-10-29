"""Installed-wheel document workflow and fixed 300-second service observation.

Invoked by deployment.py orchestrate-closeout, which owns installation/cleanup.
No synthetic incident seeding, production monkeypatch or alternate backend.
No service restart during bounded observation.
"""
import datetime,hashlib,html,json,os,platform,shutil,socket,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.closeout_checks import LIMITS,resource_check,snapshot_evidence
PY='/opt/pathquill/venv/bin/python';UNIT='pathquill.service';STATE='/var/lib/pathquill/store'
def check(value,message):
    if not value:raise RuntimeError(message)
def run(args,ok=True,timeout=12,**kwargs):
    p=subprocess.run(args,cwd='/',capture_output=True,text=True,timeout=timeout,**kwargs)
    if ok:check(p.returncode==0,'command failed: '+p.stderr[:300])
    return p
def ctl(*args):return run(['systemctl',*args]).stdout.strip()
def prop(name):return ctl('show',UNIT,'--property='+name,'--value')
def cli(op='status',ok=True,root=STATE,**fields):
    args=['runuser','-u','pathquill','--',PY,'-I','-m','pathquill.cli','--root',str(root),'--op',op]
    for name,value in fields.items():args+=['--'+name,str(value)]
    p=run(args,ok=False,timeout=6);v=json.loads(p.stdout)
    check(v['ok']==ok and (p.returncode==0)==ok,'CLI exit/reply mismatch')
    return v
if len(sys.argv)!=4 or sys.argv[1]!='worker':raise SystemExit('Use deployment.py orchestrate-closeout')
out=Path(sys.argv[2]);ns=sys.argv[3];listener=None;begin=None;last_sample=-10;samples=[];identity=None;epoch=None
report=dict(passed=False,mvp_qualified=False,cases=[],limits=LIMITS,samples=samples,
            environment=dict(system=platform.system(),release=platform.release(),machine=platform.machine(),python=platform.python_version(),utc=datetime.datetime.now(datetime.timezone.utc).isoformat()),
            boundaries=['Installed wheel and actual systemd in isolated Linux VM; explicit network namespace fixture',
                        '300-second bounded observation, not long-term operation or a leak proof; no service restart during observation',
                        'Resource gates fixed in source before measurements; CLI polling overhead is part of workload, not a throughput benchmark',
                        'One local TCP target; no WAN reachability, DNS compatibility or continuous-churn qualification',
                        'No boot enablement, VM reboot, power loss or zero-gap boot qualification; no automatic rollover'])
def start_listener():
    global listener
    check(listener is None,'listener already running')
    listener=subprocess.Popen(['ip','netns','exec',ns,PY,'-I','-c',"import socket\ns=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('198.18.0.1',29871));s.listen(128)\nwhile True:\n c,a=s.accept();c.close()"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        if run(['ip','netns','exec',ns,PY,'-I','-c',"import socket;socket.create_connection(('198.18.0.1',29871),timeout=.1).close()"],ok=False).returncode==0:return
        time.sleep(.05)
    raise TimeoutError('listener readiness')
def stop_listener():
    global listener
    if listener:
        listener.terminate();listener.wait(3);listener=None

def sample(v,force=False):
    global last_sample
    if begin is None:return
    now=time.monotonic()-begin
    if not force and now-last_sample<LIMITS['sample_interval_seconds']:return
    pid=int(prop('MainPID'));invocation=prop('InvocationID')
    check((pid,invocation)==identity and v['epoch']==epoch,'service restarted during observation')
    fields={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in Path('/proc',str(pid),'status').read_text().splitlines() if ':' in line}
    infos=[]
    for path in Path(STATE).rglob('*'):
        try:
            if path.is_file():infos.append(path.stat())
        except FileNotFoundError:pass # transient SQLite DELETE-journal names may disappear

    samples.append(dict(seconds=now,pid=pid,invocation=invocation,epoch=v['epoch'],restarts=int(prop('NRestarts')),
                        rss_kib=int(fields['VmRSS'].split()[0]),fds=len(list(Path('/proc',str(pid),'fd').iterdir())),threads=int(fields['Threads']),
                        logical_store_bytes=sum(info.st_size for info in infos),allocated_store_bytes=sum(info.st_blocks*512 for info in infos)))
    check(int(prop('MainPID'))==pid and prop('InvocationID')==invocation,'sample crossed service change');last_sample=now

def status():
    v=cli();check(v['state']=='RECORDING','recorder not healthy');sample(v);return v

def wait(predicate,seconds=12):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        v=status()
        if predicate(v):return v
        time.sleep(.15)
    raise TimeoutError('closeout condition: '+str(report.get('phase','unknown')))

def export_cycle(source,request):
    report['phase']='export_request'
    v=status();authority=dict(store=v['store_id'],epoch=v['epoch'])
    accepted=cli('export',request=request,id=source,seconds=60,**authority)
    check(accepted['export']['state']=='QUEUED','request not queued')
    report['phase']='snapshot_ready'
    def snapshot_ready(_):
        state=cli('export-status',request=request)['export']['state']
        check(state not in ('FAILED','EXPIRED','INTERRUPTED','BLOCKED'),'snapshot terminal '+state)
        return state=='SNAPSHOT_READY'
    wait(snapshot_ready)
    fixed=cli('export-read',request=request)['export'];proof=snapshot_evidence(fixed['snapshot']);raw=json.dumps(fixed['snapshot'])
    check('198.18.0.1' not in raw and 'pqmarker0' not in raw,'raw fixture leaked in sanitized snapshot')
    published=cli('export-publish',request=request,**authority)['export'];check(published['state']=='PUBLISHED','publication not complete')
    package=Path(STATE,'packages',published['package']);before={p.name:(p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns) for p in package.iterdir()}
    # Operator copy/manifest verification is deliberately outside automatic product retention.
    with tempfile.TemporaryDirectory(prefix='pq-copy-') as tmp:
        destination=Path(tmp)/'package';shutil.copytree(package,destination)
        manifest=json.loads((destination/'manifest.json').read_text())
        check({p.name:p.read_bytes() for p in destination.iterdir()}=={name:data[0] for name,data in before.items()},'operator copy mismatch')
        check(json.loads((destination/'snapshot.json').read_text())==fixed['snapshot'],'published snapshot mismatch')
        repeated=cli('export-publish',request=request,**authority)['export']
        check(repeated==published and before=={p.name:(p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns) for p in package.iterdir()},'publication replay rewrote package')
        for data in destination.iterdir():check('198.18.0.1' not in data.read_text() and 'pqmarker0' not in data.read_text(),'raw fixture leaked in copied package')
        # Actual manifest contract compared to production file bytes, not just copied-directory equality.
        check(manifest['schema']=='pathquill-package-v1','unexpected package contract')
        for name,item in manifest['files'].items():
            data=(destination/name).read_bytes();check(len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256'],'manifest mismatch')
        cli('publication-retire',request=request,package=published['package'],**authority)
        wait(lambda _:cli('publication-status',request=request)['export']['state']=='CLEANED')
        check(not package.exists(),'retired package remains')
        check(cli('export',request=request,id=source,seconds=60,**authority)['export']['state']=='RETIRED','retired request replayed')
    return dict(request=request,snapshot_bytes=len(json.dumps(fixed['snapshot']).encode()),package_bytes=published['bytes'],tcp_evidence=proof,capture_rows=len(fixed['snapshot']['observations']),passed=True)
try:
    # Installed CLI import executes under restrictive caller umask fixed by installer.
    run(['runuser','-u','pathquill','--',PY,'-I','-c',"import pathlib,pathquill;assert 'site-packages' in pathlib.Path(pathquill.__file__).parts"])
    config=Path('/etc/pathquill/config.json');config.write_text(json.dumps([dict(host='198.18.0.1',port=29871,timeout=.2,interval=.5)]));os.chmod(config,0o640)
    dropin=Path('/etc/systemd/system/pathquill.service.d');dropin.mkdir();(dropin/'namespace.conf').write_text('[Service]\nNetworkNamespacePath=/run/netns/'+ns+'\n');ctl('daemon-reload')
    start_listener();ctl('start',UNIT)
    # Initial startup can briefly be SYNCING; do not treat systemd active alone as ready.
    end=time.monotonic()+12
    while True:
        try:
            first=cli()
            if first['state']=='RECORDING' and first['health'].get('0')=='success':break
        except (OSError,ValueError,KeyError):pass
        check(time.monotonic()<end,'service readiness');time.sleep(.1)
    check(not first['incidents'],'unexpected initial incident')
    identity=(int(prop('MainPID')),prop('InvocationID'));epoch=first['epoch'];begin=time.monotonic()
    cycles=[];sources=[];report['completed_cycle_results']=cycles
    while time.monotonic()-begin<LIMITS['duration_seconds'] or len(cycles)<LIMITS['minimum_cycles']:
        report['phase']='fault_capture'
        stop_listener();failed=wait(lambda v:v['health'].get('0')!='success' and any(x['state']=='CAPTURING' for x in v['incidents']))
        capturing=next(x for x in failed['incidents'] if x['state']=='CAPTURING');source=capturing['id'];check(source not in sources,'fault did not create fresh incident');sources.append(source)
        time.sleep(.5);start_listener();wait(lambda v:v['health'].get('0')=='success')
        report['phase']='committed_seal'
        completed=wait(lambda v:any(x['id']==source and x['state']=='SEALED' and x['recovered'] for x in v['incidents']),40)
        cycles.append(export_cycle(source,'cycle_'+str(len(cycles))))
        if len(sources)>1:
            cli('delete',id=sources[-2],store=first['store_id'],epoch=epoch)
            check(not any(x['id']==sources[-2] for x in status()['incidents']),'explicit source delete incomplete')
    sample(status(),True);report['resource_summary']=resource_check(samples);report['observation_seconds']=samples[-1]['seconds'];report['completed_cycles']=len(cycles)
    begin=None # Freeze this observation before history fill or deliberate service restarts.
    check(len(cycles)>=LIMITS['minimum_cycles'],'too few real cycles')
    report['cases'].append(dict(name='real_fault_recovery_export_copy_retire_same_service',cycles=cycles,passed=True))
    # All history slots remain occupied by terminal records; reclaim does not reset history.
    current=status();source=sources[-1];authority=dict(store=current['store_id'],epoch=epoch)
    for i in range(len(cycles),32):
        request='fill_'+str(i);cli('export',request=request,id=source,seconds=60,**authority);cli('export-cancel',request=request,**authority)
    full=cli('export',ok=False,request='overflow',id=source,seconds=60,**authority)
    check(full['error']=='export_history_full','33rd request admitted')
    check(status()['capacity']['export_history']==dict(used=32,limit=32,remaining=0),'history usage incorrect')
    # Stop scheduling probes by a documented explicit service stop/config edit/start;
    # this happens AFTER the fixed observation and is not part of resource acceptance.
    ctl('stop',UNIT);stop_listener();config.write_text('[]');ctl('start',UNIT)
    end=time.monotonic()+12
    while True:
        try:
            active=cli()
            if active['state']=='RECORDING':break
        except (OSError,ValueError):pass
        check(time.monotonic()<end,'post-observation readiness');time.sleep(.1)
    check(active['epoch']!=epoch,'restart epoch unchanged')
    check(cli('export-cancel',ok=False,request='cycle_0',store=active['store_id'],epoch=epoch)['error']=='stale_epoch','old operation accepted')
    cli('store-seal',store=active['store_id'],epoch=active['epoch'])
    end=time.monotonic()+10
    while prop('MainPID')!='0':check(time.monotonic()<end,'seal did not stop');time.sleep(.1)
    archived=cli('store-archive',store=active['store_id'])['archive'];old=Path(STATE,'state.db').read_bytes()
    new='/var/lib/pathquill/new-store';created=cli('store-new',root=new,archive=STATE,store=active['store_id'])
    check(Path(STATE,'state.db').read_bytes()==old,'new store modified sealed DB')
    check(created['archive']['store_id']!=active['store_id'],'new store identity reused')
    # Fresh store reopened by same formal unit, with an explicit reviewed root override.
    (dropin/'root.conf').write_text('[Service]\nExecStart=\nExecStart='+PY+' -I -m pathquill.daemon --root '+new+' --config /etc/pathquill/config.json\n');ctl('daemon-reload');ctl('start',UNIT)
    end=time.monotonic()+10
    while True:
        try:
            fresh=cli(root=new)
            if fresh['state']=='RECORDING':break
        except (OSError,ValueError):pass
        check(time.monotonic()<end,'new store readiness');time.sleep(.1)
    check(fresh['capacity']['export_history']['used']==0 and fresh['store_id']!=active['store_id'],'fresh history not empty')
    refused=cli('export',ok=False,root=new,request='cycle_0',id=source,seconds=60,store=active['store_id'],epoch=fresh['epoch'])
    check(refused['error']=='store_mismatch','old store identity accepted');ctl('stop',UNIT)
    report['cases'].append(dict(name='32_history_refusal_seal_archive_new_store_old_authority_rejected',history=32,source='real_probe_incident',passed=True))
    report['passed']=True
except Exception as error:
    report['error']=type(error).__name__+': '+str(error).replace(str(ROOT),'<checkout>')
    try:
        import sqlite3
        with sqlite3.connect('file:'+STATE+'/state.db?mode=ro',uri=True) as db:
            report['failure_diagnostics']=dict(capture_rows=db.execute('SELECT count(*) FROM capture GROUP BY id').fetchall(),
                exports=db.execute('SELECT request,state,length(snapshot) FROM exports').fetchall(),
                control=db.execute('SELECT loss,refusals,mode FROM control').fetchone())
    except Exception:report['failure_diagnostics_unavailable']=True
finally:
    stop_listener();out.write_text(json.dumps(report,indent=2)+'\n')
sys.exit(0 if report['passed'] else 1)
