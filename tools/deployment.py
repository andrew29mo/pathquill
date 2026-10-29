"""Installed-wheel actual systemd validation in an existing disposable Linux VM."""
import datetime,hashlib,html,json,os,platform,pwd,shutil,signal,socket,stat,subprocess,sys,tempfile,time,uuid,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.supervision import run_group
from tools.service_evidence import rate_limit_proof,sealed_exit_proof
from tools.closeout_checks import cleanup_safe
FINAL=ROOT/('evidence/closeout.json' if len(sys.argv)>1 and sys.argv[1]=='orchestrate-closeout' else 'evidence/deployment.json');UNIT='pathquill.service';PY='/opt/pathquill/venv/bin/python';STATE='/var/lib/pathquill/store'
PATHS=[Path(p) for p in ('/opt/pathquill','/etc/pathquill','/var/lib/pathquill','/etc/systemd/system/pathquill.service','/etc/systemd/system/pathquill.service.d')]
def write(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n');path.with_suffix('.html').write_text('<!doctype html><meta charset="utf-8"><pre>'+html.escape(json.dumps(value,indent=2))+'</pre>')
def check(value,message):
    if not value:raise RuntimeError(message)
def run(args,check=True,timeout=15,**kwargs):return subprocess.run(args,check=check,capture_output=True,text=True,timeout=timeout,**kwargs)
def ctl(*args,check=True):return run(['systemctl',*args],check=check)
def prop(name):return ctl('show',UNIT,'--property='+name,'--value').stdout.strip()
def wait(predicate,seconds=12):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:
            value=predicate()
            if value:return value
        except (OSError,ValueError,KeyError,subprocess.CalledProcessError):pass
        time.sleep(.05)
    raise TimeoutError('deployment condition')
def source():return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*sorted((ROOT/'pathquill').glob('*.py')),*sorted((ROOT/'tests').glob('*.py')),*sorted((ROOT/'deploy').glob('*')),ROOT/'tools/deployment.py',ROOT/'tools/service_evidence.py',ROOT/'tools/closeout.py',ROOT/'tools/closeout_checks.py',ROOT/'tools/supervision.py',ROOT/'pyproject.toml'] if p.is_file()}
mode=sys.argv[1] if len(sys.argv)>1 else None
if not ((mode=='worker' and len(sys.argv)==4) or (mode in ('orchestrate','orchestrate-closeout') and len(sys.argv)==2)):write(FINAL,dict(passed=False,status='invalid_invocation'))
if mode in ('orchestrate','orchestrate-closeout') and len(sys.argv)==2:
    if FINAL.exists():
        previous=json.loads(FINAL.read_text())
        if previous.get('error'):
            folder=ROOT/('evidence/closeout-attempts' if mode=='orchestrate-closeout' else 'evidence/deployment-attempts');folder.mkdir(exist_ok=True)
            write(folder/('attempt-'+uuid.uuid4().hex[:12]+'.json'),previous)
    def terminated(*_):raise InterruptedError('orchestrator_terminated')
    signal.signal(signal.SIGTERM,terminated)
    write(FINAL,dict(passed=False,status='in_progress'));initial=source();owned=False;ns=None;result=dict(passed=False);setup={}
    try:
        check(os.getuid()==0,'run as root in disposable systemd VM');check(Path('/proc/1/comm').read_text().strip()=='systemd','actual systemd required')
        check(not any(os.path.lexists(p) for p in PATHS),'existing Pathquill installation: untouched')
        check(run(['getent','passwd','pathquill'],check=False).returncode!=0 and run(['getent','group','pathquill'],check=False).returncode!=0,'existing account: untouched')
        check(prop('LoadState')=='not-found','existing loaded service: untouched')
        clean_vm=None
        if mode=='orchestrate-closeout':
            clean_vm=json.loads(Path('/run/pathquill-clean-vm.json').read_text())
            check(clean_vm['application_absent'] and clean_vm['boot_sha256']==hashlib.sha256(Path('/proc/sys/kernel/random/boot_id').read_bytes()).hexdigest(),'missing/mismatched clean VM receipt')
        with tempfile.TemporaryDirectory(prefix='pq-deploy-') as tmp:
            tmp=Path(tmp);build=tmp/'source';build.mkdir();shutil.copytree(ROOT/'pathquill',build/'pathquill',ignore=shutil.ignore_patterns('__pycache__'));shutil.copy(ROOT/'pyproject.toml',build/'pyproject.toml')
            run(['python3','-m','venv',str(tmp/'builder')],timeout=30)
            print('Building wheel from copied, fingerprinted source',flush=True)
            run([str(tmp/'builder/bin/python'),'-I','-m','pip','wheel','--no-deps','--wheel-dir',str(tmp/'wheels'),str(build)],timeout=180,cwd='/')
            wheels=list((tmp/'wheels').glob('pathquill-*.whl'));check(len(wheels)==1,'one wheel required');wheel=wheels[0]
            with zipfile.ZipFile(wheel) as package:
                for path,digest in initial.items():
                    if path.startswith('pathquill/'):check(hashlib.sha256(package.read(path)).hexdigest()==digest,'wheel differs from tested source')
                generator=next(line for name in package.namelist() if name.endswith('.dist-info/WHEEL') for line in package.read(name).decode().splitlines() if line.startswith('Generator:'))
            setup=dict(wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),wheel_generator=generator,build_isolation=True)
            owned=True
            print('Installing fresh formal package and unit',flush=True)
            run(['sh',str(ROOT/'deploy/install.sh'),str(wheel)],timeout=90,cwd='/',umask=0o077 if mode=='orchestrate-closeout' else 0)
            setup['caller_umask']='077' if mode=='orchestrate-closeout' else '000'
            for path in Path('/opt/pathquill').rglob('*'):
                if not path.is_symlink():check(path.stat().st_uid==0 and not path.stat().st_mode & 0o022,'package is writable by non-root')
            setup['root_owned_no_group_world_write']=True
            setup['service_uid']=pwd.getpwnam('pathquill').pw_uid
            original_config=Path('/etc/pathquill/config.json').read_bytes()
            repeated=run(['sh',str(ROOT/'deploy/install.sh'),str(wheel)],check=False,timeout=15,cwd='/')
            check(repeated.returncode!=0 and Path('/etc/pathquill/config.json').read_bytes()==original_config,'repeat install overwrote configuration')
            setup['repeat_install_refused']=True
            check(Path('/etc/systemd/system/pathquill.service').read_bytes()==(ROOT/'deploy/pathquill.service').read_bytes(),'installed unit differs')
            run(['systemd-analyze','verify','/etc/systemd/system/pathquill.service'])
            code="import hashlib,json,pathlib,pathquill,sys; p=pathlib.Path(pathquill.__file__).parent; assert 'site-packages' in p.parts; print(json.dumps({x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in p.glob('*.py')}))"
            modules=json.loads(run([PY,'-I','-c',code],cwd='/').stdout)
            for name,digest in modules.items():check(initial['pathquill/'+name]==digest,'installed module differs')
            check(set(modules)=={Path(name).name for name in initial if name.startswith('pathquill/')},'installed module set differs')
            setup['installed_module_hashes']=modules;setup['isolated_site_packages_import']=True
            ns='pqdeploy-'+uuid.uuid4().hex[:8];run(['ip','netns','add',ns]);run(['ip','-n',ns,'link','set','lo','up']);run(['ip','-n',ns,'link','add','pqmarker0','type','dummy']);run(['ip','-n',ns,'addr','add','198.18.0.1/24','dev','pqmarker0']);run(['ip','-n',ns,'link','set','pqmarker0','up']);run(['ip','-n',ns,'route','add','198.19.0.0/24','dev','pqmarker0'])
            output=tmp/'worker.json'
            code=run_group([sys.executable,str(ROOT/'tools/closeout.py') if mode=='orchestrate-closeout' else __file__,'worker',str(output),ns],600 if mode=='orchestrate-closeout' else 100)
            result=json.loads(output.read_text());check(code==0 and result['passed'],'worker did not pass')
            required={'real_fault_recovery_export_copy_retire_same_service','32_history_refusal_seal_archive_new_store_old_authority_rejected'} if mode=='orchestrate-closeout' else {'default_network_and_unprivileged_service','normal_stop_cleans_processes_and_socket','explicit_namespace_probe_and_sigkill_takeover','restart_limit_then_repair','sealed_store_no_restart_loop'}
            check({c['name'] for c in result['cases']}==required and all(c['passed'] for c in result['cases']),'missing/failed deployment cases')
            result['installation']=setup
            if clean_vm is not None:result['clean_vm_provisioning']=clean_vm
            check(initial==source(),'source changed during validation');result['source']=initial
    except Exception as error:
        result['passed']=False;result.setdefault('error',type(error).__name__+': '+str(error).replace(str(ROOT),'<checkout>'));result['installation']=setup;result['source']=initial
    finally:
        try:
            if owned:
                group=prop('ControlGroup');stopped=ctl('stop',UNIT,check=False)
                members=Path('/sys/fs/cgroup'+group)/'cgroup.procs' if group else None
                check(cleanup_safe(stopped.returncode,prop('MainPID'),prop('ActiveState'),members.read_text() if members and members.exists() else ''),'service stop/cgroup incomplete: preserve installation')
                ctl('reset-failed',UNIT,check=False)
                for path in reversed(PATHS):
                    if path.is_dir():shutil.rmtree(path)
                    elif os.path.lexists(path):path.unlink()
                ctl('daemon-reload')
                account=run(['getent','passwd','pathquill'],check=False)
                if account.returncode==0:run(['userdel','pathquill'])
                if run(['getent','group','pathquill'],check=False).returncode==0:run(['groupdel','pathquill'])
                check(not any(os.path.lexists(p) for p in PATHS),'installation cleanup incomplete')
                check(run(['getent','passwd','pathquill'],check=False).returncode!=0 and run(['getent','group','pathquill'],check=False).returncode!=0,'account cleanup incomplete')
            if ns and Path('/run/netns',ns).exists():
                check(not run(['ip','netns','pids',ns]).stdout.strip(),'namespace still occupied');run(['ip','netns','del',ns])
            result['orchestrator_cleanup']=True
        except Exception as error:result['passed']=False;result['cleanup_error']=type(error).__name__+': '+str(error)
        write(FINAL,result)
        if os.getuid()==0:os.chown(FINAL,501,501);os.chown(FINAL.with_suffix('.html'),501,501)
    sys.exit(0 if result['passed'] else 1)
if mode!='worker' or len(sys.argv)!=4:raise SystemExit('Usage: deployment.py orchestrate in disposable systemd VM')
ns=sys.argv[3];out=Path(sys.argv[2]);server=None
result=dict(passed=False,mvp_qualified=False,cases=[],environment=dict(system=platform.system(),release=platform.release(),python=platform.python_version(),systemd=ctl('--version').stdout.splitlines()[0],utc=datetime.datetime.now(datetime.timezone.utc).isoformat()),limits=['Existing Colima Linux VM with fresh Pathquill paths, not a clean OS/VM or boot test','Normal unit inherits VM network; namespace drop-in is explicit test topology, not PrivateNetwork','Installed wheel used by actual systemd and CLI; source unit tests are separately executed and fingerprint-bound to wheel','Finite restart/stop observations, no hard latency or resource-leak guarantee','No VM reboot, power loss, systemd boot enablement, independent backup restore or production qualification'])
def cli(op='status',ok=True,**fields):
    args=['runuser','-u','pathquill','--',PY,'-I','-m','pathquill.cli','--root',STATE,'--op',op]
    for name,value in fields.items():args+=['--'+name,str(value)]
    p=run(args,check=False,timeout=5,cwd='/');reply=json.loads(p.stdout);check((p.returncode==0)==ok and reply['ok']==ok,'installed CLI exit/reply mismatch');return reply
def ready():
    if prop('ActiveState')!='active':return False
    value=cli();return value if value['state']=='RECORDING' else False
def pid():return int(prop('MainPID'))
def process_flags(process):
    return {line.split(':',1)[0]:line.split(':',1)[1].strip() for line in Path('/proc',str(process),'status').read_text().splitlines() if ':' in line}
def link_names(value):return {bytes.fromhex(v['attributes'].get('3','')).rstrip(b'\0').decode() for v in value['view']['links'].values()}
def reset_limits():
    outcome=ctl('reset-failed',UNIT,check=False)
    # systemd may unload a normally stopped unit; reset-failed then reports
    # 'not loaded'. It is harmless only when already inactive with no process.
    check(outcome.returncode==0 or (prop('ActiveState')=='inactive' and pid()==0),'cannot reset failed service')

def stop_and_check():
    group=prop('ControlGroup');old=pid();ctl('stop',UNIT);check(prop('MainPID')=='0' and not Path(STATE,'control.sock').exists(),'stop left process/socket')
    if group:
        members=Path('/sys/fs/cgroup'+group)/'cgroup.procs';check(not members.exists() or not members.read_text().strip(),'cgroup occupied')
    check(not Path('/proc',str(old)).exists(),'old PID survives stop')
    time.sleep(2.2);check(prop('MainPID')=='0' and prop('ActiveState')=='inactive','normal stop auto-restarted')
try:
    # Run source unit tests, then bind every installed module to those same bytes.
    import unittest
    sys.path.insert(0,str(ROOT));tests=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover(str(ROOT/'tests'),top_level_dir=str(ROOT)));check(tests.wasSuccessful(),'source tests failed');result['tests']=tests.testsRun
    result['phase']='default_service';ctl('start',UNIT);first=wait(ready);
    check(prop('FragmentPath')=='/etc/systemd/system/pathquill.service' and not prop('DropInPaths'),'unexpected unit override')
    policy={name:prop(name) for name in ('Restart','RestartUSec','StartLimitBurst','StartLimitIntervalUSec','RestartPreventExitStatus','SuccessExitStatus','KillMode')}
    check(policy['Restart']=='on-failure' and policy['RestartUSec']=='1s' and policy['StartLimitBurst']=='3' and policy['StartLimitIntervalUSec']=='30s' and '78' in policy['RestartPreventExitStatus'].split() and '78' in policy['SuccessExitStatus'].split() and policy['KillMode']=='control-group','applied policy differs')
    result['applied_policy']=policy
    process=pid();flags=process_flags(process)
    uid=pwd.getpwnam('pathquill').pw_uid
    check(uid!=0 and all(int(v)==uid for v in flags['Uid'].split()),'service root/wrong UID')
    check(int(flags['CapEff'],16)==0 and flags['NoNewPrivs']=='1','service retains privileges')
    check(os.stat('/proc/'+str(process)+'/ns/net').st_ino==os.stat('/proc/1/ns/net').st_ino,'default unit observes wrong namespace')
    reference={x['ifname'] for x in json.loads(run(['ip','-j','link']).stdout)};check(link_names(first)==reference,'default link view differs from independent ip')
    command=Path('/proc',str(process),'cmdline').read_bytes().split(b'\0');check(command[:4]==[PY.encode(),b'-I',b'-m',b'pathquill.daemon'],'service not installed isolated module')
    check(Path('/proc',str(process),'cwd').resolve()==Path('/'),'service cwd depends on source')
    environment=Path('/proc',str(process),'environ').read_bytes().split(b'\0');check(not any(v.startswith((b'PYTHONPATH=',b'PYTHONHOME=')) for v in environment),'source path injected')
    check(stat.S_IMODE(Path(STATE).stat().st_mode)==0o700 and stat.S_IMODE(Path(STATE,'control.sock').stat().st_mode)==0o600,'private modes wrong')
    denied=run(['runuser','-u','pathquill','--',PY,'-I','-c',"open('/etc/pathquill/config.json','a').write('x')"],check=False);check(denied.returncode!=0,'service account can write config')
    result['cases'].append(dict(name='default_network_and_unprivileged_service',uid=uid,cap_eff_zero=True,no_new_privs=True,vm_network_namespace_match=True,independent_link_count=len(reference),config_write_denied=True,passed=True))
    result['phase']='normal_stop';stop_and_check();result['cases'].append(dict(name='normal_stop_cleans_processes_and_socket',observation_seconds=2.2,passed=True))
    result['phase']='namespace_and_crash'
    seed="from pathquill.publication import PublicationRecorder; import json; r=PublicationRecorder('"+STATE+"'); k=r.incident({'endpoints':['198.18.0.1']},0); r.finish(k,30,r.epoch,30); print(json.dumps({'source':k})); r.close()"
    source_id=json.loads(run(['runuser','-u','pathquill','--',PY,'-I','-c',seed],cwd='/').stdout)['source']
    Path('/etc/pathquill/config.json').write_text(json.dumps([dict(host='198.18.0.1',port=29871,timeout=.1,interval=.2)]));os.chmod('/etc/pathquill/config.json',0o640)
    server=subprocess.Popen(['ip','netns','exec',ns,PY,'-I','-c',"import socket; s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('198.18.0.1',29871));s.listen()\nwhile True:\n c,a=s.accept();c.close()"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    wait(lambda:run(['ip','netns','exec',ns,PY,'-I','-c',"import socket; socket.create_connection(('198.18.0.1',29871),timeout=.1).close()"],check=False).returncode==0)
    drop=Path('/etc/systemd/system/pathquill.service.d');drop.mkdir();(drop/'10-validation.conf').write_text('[Service]\nNetworkNamespacePath=/run/netns/'+ns+'\n');ctl('daemon-reload');ctl('start',UNIT)
    current=wait(lambda:(v if (v:=ready()) and v['health'].get('0')=='success' else False))
    check(os.stat('/proc/'+str(pid())+'/ns/net').st_ino==os.stat('/run/netns/'+ns).st_ino,'test target namespace differs')
    check(link_names(current)=={x['ifname'] for x in json.loads(run(['ip','-n',ns,'-j','link']).stdout)} and 'pqmarker0' in link_names(current),'isolated interface view wrong')
    routes=current['view']['routes'].values();check(any(v['family']==2 and v['dst_prefix']==24 and v['attributes'].get('1')=='c6130000' for v in routes),'fixture route not observed')
    old_pid=pid();old_invocation=prop('InvocationID');old_epoch=current['epoch'];identity=current['store_id'];old_restarts=int(prop('NRestarts'))
    cli('export',request='restart_pending',id=source_id,seconds=60,epoch=old_epoch,store=identity)
    begin=time.monotonic();ctl('kill','--kill-who=main','--signal=SIGKILL',UNIT)
    restored=wait(lambda:(v if (v:=ready()) and v['epoch']!=old_epoch else False));elapsed=time.monotonic()-begin
    new_pid=pid();check(new_pid!=old_pid and prop('InvocationID')!=old_invocation and int(prop('NRestarts'))>old_restarts,'systemd did not create successor')
    check(not Path('/proc',str(old_pid)).exists() and restored['store_id']==identity,'old process survives or store identity changed')
    check(cli('export-status',request='restart_pending')['export']['state']=='INTERRUPTED','old queued export revived')
    check(not any(h['id']==source_id for h in restored['capacity']['holds']),'old export hold leaked')
    check(cli('export-cancel',False,request='restart_pending',epoch=old_epoch,store=identity)['error']=='stale_epoch','old operation accepted')
    before=(pid(),prop('InvocationID'));flags=process_flags(before[0]);group_memory=int(prop('MemoryCurrent'));after=(pid(),prop('InvocationID'));check(before==after,'RSS identity changed')
    result['cases'].append(dict(name='explicit_namespace_probe_and_sigkill_takeover',namespace_matches_target=True,probe_success=True,observed_restart_cli_seconds=elapsed,main_rss_kib=int(flags['VmRSS'].split()[0]),cgroup_memory_current_bytes=group_memory,old_export_interrupted=True,old_operation_rejected=True,passed=True))
    result['phase']='restart_limit';stop_and_check();Path('/etc/pathquill/config.json').write_text('[{"host":"127.0.0.1","port":0,"timeout":0.1,"interval":0.2}]');since=time.time();since_us=time.monotonic_ns()//1000;boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();reset_limits();ctl('start',UNIT,check=False)
    def current_limit_proof():
        if prop('ActiveState')!='failed' or pid()!=0:return False
        lines=run(['journalctl','-u',UNIT,'--since','@'+str(since),'-o','json','--no-pager']).stdout.splitlines()
        return rate_limit_proof([json.loads(line) for line in lines],UNIT,boot,since_us,int(policy['StartLimitBurst']))
    proof=wait(current_limit_proof,seconds=15);count=int(prop('NRestarts'))
    time.sleep(2.2);check(int(prop('NRestarts'))==count and pid()==0 and prop('ActiveState')=='failed','restart loop not limited')
    result['cases'].append(dict(name='restart_limit_then_repair',result=prop('Result'),restart_count=count,**proof,quiet_observation_seconds=2.2,passed=True))
    Path('/etc/pathquill/config.json').write_text('[]');reset_limits();ctl('start',UNIT);repaired=wait(ready)
    result['phase']='sealed_store'
    sealed=cli('store-seal',epoch=repaired['epoch'],store=repaired['store_id']);check(sealed['lifecycle']=='SEALED','seal not accepted');wait(lambda:prop('ActiveState')=='inactive')
    time.sleep(2.2);check(pid()==0 and not Path(STATE,'control.sock').exists(),'sealed store restarted')
    sealed_digest=hashlib.sha256(Path(STATE,'state.db').read_bytes()).hexdigest()
    reset_limits();sealed_since=time.time();sealed_us=time.monotonic_ns()//1000;ctl('start',UNIT,check=False)
    def current_sealed_proof():
        if prop('ActiveState')!='inactive' or pid()!=0:return False
        lines=run(['journalctl','-u',UNIT,'--since','@'+str(sealed_since),'-o','json','--no-pager']).stdout.splitlines()
        return sealed_exit_proof([json.loads(line) for line in lines],UNIT,boot,sealed_us)
    proof=wait(current_sealed_proof);count=int(prop('NRestarts'));time.sleep(2.2)
    check(pid()==0 and prop('ActiveState')=='inactive' and int(prop('NRestarts'))==count==0,'sealed startup restart loop');current_sealed_proof()
    check(hashlib.sha256(Path(STATE,'state.db').read_bytes()).hexdigest()==sealed_digest,'sealed startup changed database')
    result['cases'].append(dict(name='sealed_store_no_restart_loop',sealed_database_unchanged=True,**proof,restart_count=count,quiet_observation_seconds=2.2,passed=True))
    result['passed']=True;result['phase']='complete'
except Exception as error:result['error']=type(error).__name__+': '+str(error).replace(str(ROOT),'<checkout>')
finally:
    if server:
        if server.poll() is None:server.terminate()
        server.wait(5)
    write(out,result)
sys.exit(0 if result['passed'] else 1)
