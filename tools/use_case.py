"""Single real installed-service use case. Run via deployment.py orchestrate-use-case."""
import datetime,hashlib,ipaddress,json,os,platform,shutil,socket,subprocess,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.use_case_checks import verify_package
PY='/opt/pathquill/venv/bin/python';UNIT='pathquill.service';STATE='/var/lib/pathquill/store'
def check(v,message):
    if not v:raise RuntimeError(message)
def run(args,ok=True,timeout=10):
    p=subprocess.run(args,cwd='/',capture_output=True,text=True,timeout=timeout)
    if ok:check(p.returncode==0,'command_failed')
    return p

def ctl(*args):return run(['systemctl',*args]).stdout.strip()
def prop(name):return ctl('show',UNIT,'--property='+name,'--value')
if len(sys.argv)!=4 or sys.argv[1]!='worker':raise SystemExit('Use deployment.py orchestrate-use-case in a disposable Linux VM')
out=Path(sys.argv[2]);ns=sys.argv[3];listener=None
work=ROOT/'results/use-case/runs'/uuid.uuid4().hex;work.mkdir(mode=0o700,parents=True)
# On the mounted checkout, keep local private records readable by its owner only.
os.chown(work,501,501)
trace=work/'private-cli.jsonl';trace.touch(mode=0o600);os.chown(trace,501,501)
report=dict(passed=False,cases=[],steps=[],environment=dict(system=platform.system(),release=platform.release(),python=platform.python_version(),utc=datetime.datetime.now(datetime.timezone.utc).isoformat()),boundaries=['Existing isolated Colima Linux VM, fresh application paths; not a clean OS install','Actual installed wheel/systemd/CLI, explicit namespace fixture; no synthetic seeded incident or alternate recorder','One local IPv4 TCP refusal/recovery; not WAN, DNS, load or long-term qualification','No VM reboot, power loss, autostart or zero-gap boot test','Raw CLI/store/archive data remain private; public bytes are checked fixture output, not universal anonymity proof'])
phase='setup';start=time.monotonic();private_values=set()
class NotReady(Exception):pass

def cli(op='status',ok=True,root=STATE,**fields):
    args=['runuser','-u','pathquill','--',PY,'-I','-m','pathquill.cli','--root',root,'--op',op]
    for key,value in fields.items():args+=['--'+key,str(value)]
    p=run(args,False,6)
    with trace.open('a') as stream:stream.write(json.dumps(dict(op=op,root=root,fields=fields,returncode=p.returncode,stdout=p.stdout,stderr=p.stderr))+'\n')
    if op=='status' and not p.stdout and any(text in p.stderr for text in ('FileNotFoundError:', 'ConnectionRefusedError:')):raise NotReady()
    reply=json.loads(p.stdout);check(reply['ok']==ok and (p.returncode==0)==ok,'CLI_reply_exit_mismatch')
    return reply

def wait(predicate,seconds=12,root=STATE):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:v=cli(root=root)
        except NotReady:
            time.sleep(.1);continue
        if predicate(v):return v
        time.sleep(.1)
    raise TimeoutError(phase)
def step(name,**facts):report['steps'].append(dict(name=name,elapsed_seconds=time.monotonic()-start,**facts))
def listen():
    global listener
    listener=subprocess.Popen(['ip','netns','exec',ns,PY,'-I','-c',"import socket\ns=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('198.18.0.1',29871));s.listen(128)\nwhile True:\n c,a=s.accept();c.close()"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    end=time.monotonic()+5
    while time.monotonic()<end:
        if run(['ip','netns','exec',ns,PY,'-I','-c',"import socket;socket.create_connection(('198.18.0.1',29871),timeout=.1).close()"],False).returncode==0:return
        time.sleep(.05)
    raise TimeoutError('fixture_listener')
def stop_listener():
    global listener
    if listener:listener.terminate();listener.wait(3);listener=None

def export(source,request,authority):
    cli('export',request=request,id=source,seconds=60,**authority)
    def ready(_):
        state=cli('export-status',request=request)['export']['state']
        check(state not in ('FAILED','EXPIRED','BLOCKED','INTERRUPTED'),'snapshot_failed')
        return state=='SNAPSHOT_READY'
    wait(ready);published=cli('export-publish',request=request,**authority)['export'];check(published['state']=='PUBLISHED','not_published')
    return published,Path(STATE,'packages',published['package'])
try:
    import unittest
    suite=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover(str(ROOT/'tests'),top_level_dir=str(ROOT)))
    check(suite.wasSuccessful(),'source_tests_failed');report['tests']=suite.testsRun
    run(['ip','-n',ns,'link','set','pqmarker0','down']);run(['ip','-n',ns,'link','set','pqmarker0','name','pqprivate0']);run(['ip','-n',ns,'link','set','pqprivate0','address','02:11:22:33:44:55']);run(['ip','-n',ns,'link','set','pqprivate0','up'])
    private_values.update(['pqprivate0','02:11:22:33:44:55','021122334455','198.18.0.1','c6120001',STATE])
    for row in json.loads(run(['ip','-n',ns,'-j','address']).stdout):
        private_values.add(row['ifname']) if row['ifname']!='lo' else None
        for address in row['addr_info']:
            ip=ipaddress.ip_address(address['local']);private_values.update((str(ip),ip.packed.hex()))
    config=Path('/etc/pathquill/config.json');config.write_text(json.dumps([dict(host='198.18.0.1',port=29871,timeout=.2,interval=.5)]));os.chmod(config,0o640)
    drop=Path('/etc/systemd/system/pathquill.service.d');drop.mkdir();(drop/'namespace.conf').write_text('[Service]\nNetworkNamespacePath=/run/netns/'+ns+'\n');ctl('daemon-reload');listen();ctl('start',UNIT)
    first=wait(lambda v:v['state']=='RECORDING' and v['health'].get('0')=='success');identity=(prop('MainPID'),prop('InvocationID'));authority=dict(store=first['store_id'],epoch=first['epoch']);private_values.update(authority.values());step('healthy_installed_service',unprivileged_uid=int(run(['id','-u','pathquill']).stdout))
    # Ensure initial state/probes are committed before the refusal.
    time.sleep(1);phase='tcp_failure';stop_listener();failed=wait(lambda v:any(x['state']=='CAPTURING' for x in v['incidents']) and v['health'].get('0')=='refused')
    source=next(x['id'] for x in failed['incidents'] if x['state']=='CAPTURING');private_values.add(source);step('tcp_refused_capture',outcome='refused')
    time.sleep(1);listen();phase='recovery';wait(lambda v:v['health'].get('0')=='success');step('tcp_success_after_recovery')
    phase='committed_seal';wait(lambda v:any(x['id']==source and x['state']=='SEALED' and x['recovered'] for x in v['incidents']),40);step('sealed_recovered')
    phase='export';published,package=export(source,'incident_demo',authority);files={p.name:p.read_bytes() for p in package.iterdir()};private_values.add(published['package'])
    proof=verify_package(files,private_values)
    # Copy exactly the actual verified product package. Raw CLI is a separate private file.
    copied=work/'public-package';copied.mkdir(mode=0o700);os.chown(copied,501,501)
    for name,data in files.items():
        p=copied/name;p.write_bytes(data);p.chmod(0o600);os.chown(p,501,501)
    check(verify_package({p.name:p.read_bytes() for p in copied.iterdir()},private_values)==proof,'copy_changed')
    step('published_and_copy_verified',**proof);report['sample']=dict(directory=str(copied.relative_to(ROOT)),**proof)
    check((prop('MainPID'),prop('InvocationID'))==identity,'service_restarted_before_export')
    report['cases'].append(dict(name='tcp_failure_recovery_export',passed=True))
    cli('publication-retire',request='incident_demo',package=published['package'],**authority);phase='retirement';wait(lambda _:cli('publication-status',request='incident_demo')['export']['state']=='CLEANED')
    check(not package.exists(),'retired_files_remain');check(cli()['capacity']['snapshots']['bytes']==0 and cli()['capacity']['publications']['reserved_bytes']==0,'credit_not_released')
    # Fill history from the still-present real incident, then explicitly reclaim raw data.
    for i in range(1,32):
        request='history_'+str(i);cli('export',request=request,id=source,seconds=60,**authority);cli('export-cancel',request=request,**authority)
    check(cli('export',False,request='overflow',id=source,seconds=60,**authority)['error']=='export_history_full','overflow_accepted')
    check(cli()['capacity']['export_history']==dict(used=32,limit=32,remaining=0),'history_count')
    cli('delete',id=source,**authority);state=cli();check(not state['incidents'] and not state['capacity']['holds'],'raw_data_or_holds_remain')
    check(state['capacity']['export_history']['used']==32,'delete_released_history')
    check(cli('export',request='incident_demo',id=source,seconds=60,**authority)['export']['state']=='RETIRED','old_request_replayed')
    verify_package({p.name:p.read_bytes() for p in copied.iterdir()},private_values);step('retired_and_raw_reclaimed',history_used=32,history_limit=32,request_33_error='export_history_full',copied_package_preserved=True)
    report['cases'].append(dict(name='copy_verify_retire_and_raw_reclaim',passed=True))
    # Remove active probes via the documented stop/edit/start procedure, after export.
    ctl('stop',UNIT);stop_listener();config.write_text('[]');ctl('start',UNIT);phase='idle_restart';idle=wait(lambda v:v['state']=='RECORDING');new_auth=dict(store=idle['store_id'],epoch=idle['epoch'])
    check(cli('export-cancel',False,request='incident_demo',**authority)['error']=='stale_epoch','old_epoch_accepted')
    cli('store-seal',**new_auth)
    end=time.monotonic()+10
    while prop('MainPID')!='0':check(time.monotonic()<end,'seal_not_stopped');time.sleep(.1)
    cli('store-archive',store=idle['store_id']);old=Path(STATE,'state.db').read_bytes();new='/var/lib/pathquill/new-store';created=cli('store-new',root=new,archive=STATE,store=idle['store_id'])
    check(Path(STATE,'state.db').read_bytes()==old,'archive_changed')
    (drop/'root.conf').write_text('[Service]\nExecStart=\nExecStart='+PY+' -I -m pathquill.daemon --root '+new+' --config /etc/pathquill/config.json\n');ctl('daemon-reload');ctl('start',UNIT)
    fresh=wait(lambda v:v['state']=='RECORDING',root=new)
    check(fresh['store_id']!=idle['store_id'] and fresh['capacity']['export_history']['used']==0,'new_store_not_fresh')
    check(cli('export',False,root=new,request='incident_demo',id=source,seconds=60,store=idle['store_id'],epoch=fresh['epoch'])['error']=='store_mismatch','old_store_accepted')
    check(cli('export',False,root=new,request='incident_demo',id=source,seconds=60,store=fresh['store_id'],epoch=fresh['epoch'])['error']=='not_sealed','old_source_accepted')
    ctl('stop',UNIT);step('manual_seal_archive_new_store',old_history=32,new_history=0,archive_database_unchanged=True,old_epoch_error='stale_epoch',old_store_error='store_mismatch',old_source_error='not_sealed')
    # Prove that the new store can accept new work, not only start with empty history.
    config.write_text(json.dumps([dict(host='198.18.0.1',port=29871,timeout=.2,interval=.5)]));listen();ctl('start',UNIT)
    phase='fresh_store_new_incident';fresh=wait(lambda v:v['state']=='RECORDING' and v['health'].get('0')=='success',root=new)
    stop_listener();fault=wait(lambda v:any(x['state']=='CAPTURING' for x in v['incidents']) and v['health'].get('0')=='refused',root=new)
    fresh_source=next(x['id'] for x in fault['incidents'] if x['state']=='CAPTURING');listen()
    wait(lambda v:any(x['id']==fresh_source and x['state']=='SEALED' and x['recovered'] for x in v['incidents']),40,root=new)
    fresh_auth=dict(store=fresh['store_id'],epoch=fresh['epoch'])
    accepted=cli('export',root=new,request='new_work',id=fresh_source,seconds=60,**fresh_auth)
    check(accepted['export']['state']=='QUEUED','new_work_not_accepted')
    cli('export-cancel',root=new,request='new_work',**fresh_auth)
    check(cli(root=new)['capacity']['export_history']['used']==1,'new_work_history_missing')
    ctl('stop',UNIT);stop_listener();check(Path(STATE,'state.db').read_bytes()==old,'new_work_changed_archive')
    step('new_store_accepts_fresh_real_work',history_used=1,old_archive_database_unchanged=True)
    report['cases'].append(dict(name='history_full_manual_handoff_new_work',passed=True));report['passed']=True
except Exception as error:report['error']=type(error).__name__+': '+str(error).replace(str(ROOT),'<checkout>');report['failed_phase']=phase
finally:
    stop_listener();report['elapsed_seconds']=time.monotonic()-start;out.write_text(json.dumps(report,indent=2)+'\n')
sys.exit(0 if report['passed'] else 1)
