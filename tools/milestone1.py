"""Real daemon milestone fixture; run under sudo unshare --net in a Linux VM."""
import hashlib,html,json,os,signal,socket,subprocess,sys,tempfile,time,unittest,struct,platform,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pathquill.cli import call
from pathquill.core import boottime

def check(v,message):
    if not v:raise RuntimeError(message)
def command(*args):subprocess.run(['sudo','ip',*args],check=True,timeout=5)
r=dict(passed=False,mvp_qualified=False,environment=dict(system=platform.system(),release=platform.release(),machine=platform.machine(),python=platform.python_version(),utc=datetime.datetime.now(datetime.timezone.utc).isoformat()),cases=[],limits=['Normal kernel notifications only; loss/churn controls separately injected in tests','State converges after two equal quiet dumps; no atomic cross-table snapshot claim','DNS daemon probes explicit IPv4 UDP only; no general resolver compatibility claim','No systemd, VM reboot of daemon, power-loss, suspend or long-term operation qualification'])
proc=None;server=None
initial=ROOT/'evidence/milestone1.json';initial.write_text(json.dumps(dict(passed=False,status='in_progress'))+'\n')
initial.with_suffix('.html').write_text('<pre>in_progress</pre>')
if os.getuid()==0:os.chown(initial,501,501);os.chown(initial.with_suffix('.html'),501,501)
try:
    command('link','set','lo','up');command('link','add','pq2','type','dummy');command('addr','add','10.55.0.1/24','dev','pq2');command('link','set','pq2','up')
    os.setgroups([]);os.setgid(501);os.setuid(501)
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),top_level_dir=str(ROOT));result=unittest.TextTestRunner(verbosity=1).run(suite);check(result.wasSuccessful(),'tests failed');r['tests']=result.testsRun
    with tempfile.TemporaryDirectory(prefix='pq-daemon-') as tmp:
        tmp=Path(tmp);server=socket.socket();server.bind(('127.0.0.1',0));port=server.getsockname()[1];server.close();server=None
        config=tmp/'config.json';config.write_text(json.dumps([dict(host='127.0.0.1',port=port,timeout=.2,interval=.5),dict(host='10.55.0.2',port=80,timeout=1.5,interval=.5)]))
        # The slow target's listener will remain absent; stop scheduling it after concurrency test.
        log=open(tmp/'daemon.log','wb');proc=subprocess.Popen([sys.executable,'-m','pathquill.daemon','--root',str(tmp/'store'),'--config',str(config)],cwd=ROOT,stdout=log,stderr=log);log.close()
        def status():
            check(proc.poll() is None,'daemon exited: '+(tmp/'daemon.log').read_text());return call(tmp/'store')
        def wait(predicate,seconds=12):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                try:
                    value=status()
                    if predicate(value):return value
                except (OSError,ValueError):pass
                time.sleep(.05)
            raise TimeoutError('daemon condition: '+(tmp/'daemon.log').read_text())
        first=wait(lambda v:v['state']=='RECORDING' and bool(v['incidents']))
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as malformed:
            malformed.settimeout(2);malformed.connect(str(tmp/'store/control.sock'));malformed.sendall(b'null');malformed.recv(1024)
        check(status()['epoch']==first['epoch'],'malformed request restarted daemon')
        import sqlite3
        raw=sqlite3.connect('file:'+str(tmp/'store/state.db')+'?mode=ro',uri=True)
        check(any(json.loads(x[0]).get('kind')=='state_object' for x in raw.execute('SELECT body FROM observations')),'state projection not persisted');raw.close()
        # While a bounded slow connect is outstanding, mutate real network state.
        inflight=wait(lambda v:any(p['target']==1 and p['started'] is not None and not p['done'] for p in v['pending']))
        slow=next(p for p in inflight['pending'] if p['target']==1);before_progress=inflight['committed']
        mutation_begin=boottime();begin=time.monotonic();command('addr','add','10.55.0.3/24','dev','pq2')
        changed=wait(lambda v:v['committed']>before_progress and v['notifications']>0 and any(x['attributes'].get('1')=='0a370003' for x in (v['view'] or {}).get('addresses',{}).values()))
        changed_observed=boottime();add_elapsed=time.monotonic()-begin
        check(changed['committed']>before_progress,'no committed progress')
        resynced=call(tmp/'store','resync');stale=wait(lambda v:any(x['target']==1 and x['generation']==slow['generation'] and x['stale'] and x['start']==slow['started'] for x in v['results']))
        slow_result=next(x for x in stale['results'] if x['target']==1 and x['start']==slow['started'])
        check(slow_result['start']<=mutation_begin<=changed_observed<slow_result['end'],'collection did not complete during outstanding slow probe')
        check(slow_result['end']-slow_result['start']>=1.0 and add_elapsed<1.0,'slow probe overlap was not established')
        check('1' not in stale['health'],'stale result changed health')
        raw=sqlite3.connect('file:'+str(tmp/'store/state.db')+'?mode=ro',uri=True)
        persisted=[json.loads(x[0]) for x in raw.execute('SELECT body FROM observations')];raw.close()
        check(not any(x.get('target')==1 and x.get('generation')==slow['generation'] for x in persisted),'stale result persisted')
        command('addr','del','10.55.0.3/24','dev','pq2')
        removed=wait(lambda v:v['state']=='RECORDING' and not any(x['attributes'].get('1')=='0a370003' for x in v['view']['addresses'].values()))
        links=json.loads(subprocess.check_output(['ip','-j','link','show'],text=True))
        addresses=json.loads(subprocess.check_output(['ip','-j','address','show'],text=True))
        expected={(row['ifindex'],x['local'],x['prefixlen']) for row in addresses for x in row['addr_info']}
        import ipaddress
        actual={(x['index'],str(ipaddress.ip_address(bytes.fromhex(x['attributes'].get('2',x['attributes']['1'])))),x['prefix']) for x in removed['view']['addresses'].values()}
        check(expected==actual,'independent address view differs')
        actual_links={x['index']:bytes.fromhex(x['attributes']['3']).rstrip(b'\0').decode() for x in removed['view']['links'].values()}
        check(actual_links=={x['ifindex']:x['ifname'] for x in links},'independent link view differs')
        routes=[]
        for family in ('-4','-6'):routes+=json.loads(subprocess.check_output(['ip','-j',family,'route','show','table','all'],text=True))
        check(len(routes)==len(removed['view']['routes']),'independent route count differs')
        r['cases'].append(dict(name='real_address_add_delete_and_stale_result',notifications=removed['notifications'],stale=stale['stale_results'],add_observation_seconds=add_elapsed,stale_health_unchanged=True,stale_not_persisted=True,mutation_begin=mutation_begin,changed_observed=changed_observed,slow_result=slow_result,writer_progress_delta=changed['committed']-before_progress,independent_links_addresses=True,independent_route_count=len(routes),passed=True))
        # Separate one-target daemon so slow endpoint cannot mask recovery.
        proc.terminate();check(proc.wait(5)==0,'shutdown failed');check(not (tmp/'store/control.sock').exists(),'socket survived')
        server=socket.socket();server.bind(('127.0.0.1',port));server.listen()
        config.write_text(json.dumps([dict(host='127.0.0.1',port=port,timeout=.2,interval=.5)]))
        log=open(tmp/'daemon2.log','wb');proc=subprocess.Popen([sys.executable,'-m','pathquill.daemon','--root',str(tmp/'recovery'),'--config',str(config)],cwd=ROOT,stdout=log,stderr=log);log.close()
        # Rebind helpers to the second store/log.
        def status():
            check(proc.poll() is None,'daemon exited: '+(tmp/'daemon2.log').read_text());return call(tmp/'recovery')
        wait(lambda v:v['health'].get('0')=='success');server.close();server=None
        failure=wait(lambda v:any(x['state']=='CAPTURING' for x in v['incidents']))
        import sqlite3
        raw=sqlite3.connect('file:'+str(tmp/'recovery/state.db')+'?mode=ro',uri=True)
        first_time,end_time=raw.execute("SELECT first,end FROM incidents WHERE state='CAPTURING'").fetchone();raw.close()
        server=socket.socket();server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);server.bind(('127.0.0.1',port));server.listen(128)
        # Keep accepting so backlog pressure cannot create a second artificial outage.
        server.settimeout(.2)
        import threading
        live=True
        def accept():
            while live:
                try:c,_=server.accept();c.close()
                except socket.timeout:pass
        thread=threading.Thread(target=accept,daemon=True);thread.start()
        completed=wait(lambda v:any(x['state']=='SEALED' and x['recovered'] for x in v['incidents']),40)
        from pathquill.core import boottime
        raw=sqlite3.connect('file:'+str(tmp/'recovery/state.db')+'?mode=ro',uri=True)
        progress=raw.execute('SELECT seq,t,body FROM observations WHERE seq=?',(completed['committed'],)).fetchone();raw.close()
        check(progress is not None and progress[1]>=end_time and json.loads(progress[2])['kind']=='progress','no persisted deadline barrier')
        sealed_observed=boottime();check(sealed_observed>=end_time and end_time>=first_time+30,'sealed before real deadline')
        live=False;thread.join(2);server.close();server=None
        proc.terminate();check(proc.wait(5)==0,'shutdown failed');check(not (tmp/'recovery/control.sock').exists(),'socket cleanup failed')
        r['cases'].append(dict(name='real_failure_recovery_and_committed_seal',committed=completed['committed'],window_seconds=end_time-first_time,persisted_barrier_sequence=progress[0],persisted_barrier_after_deadline=progress[1]-end_time,sealed_observed_after_deadline=sealed_observed-end_time,incidents=completed['incidents'],passed=True))
        udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);udp.bind(('127.0.0.1',0));udp.settimeout(.2)
        dns_live=True
        def dns_answer():
            while dns_live:
                try:
                    data,peer=udp.recvfrom(4096);udp.sendto(data[:2]+b'\x81\x82'+data[4:],peer)
                except socket.timeout:pass
        dns_thread=threading.Thread(target=dns_answer,daemon=True);dns_thread.start()
        config.write_text(json.dumps([dict(kind='dns',host='127.0.0.1',port=udp.getsockname()[1],timeout=.2,interval=.5)]))
        log=open(tmp/'dns.log','wb');proc=subprocess.Popen([sys.executable,'-m','pathquill.daemon','--root',str(tmp/'dns'),'--config',str(config)],cwd=ROOT,stdout=log,stderr=log);log.close()
        def status():
            check(proc.poll() is None,'DNS daemon exited: '+(tmp/'dns.log').read_text());return call(tmp/'dns')
        dns_result=wait(lambda v:v['health'].get('0')=='dns_error' and bool(v['incidents']))
        proc.terminate();check(proc.wait(5)==0,'DNS shutdown failed');dns_live=False;dns_thread.join(2);udp.close()
        r['cases'].append(dict(name='real_daemon_DNS_trigger',passed=True))
    r['passed']=True
except Exception as e:r['error']=type(e).__name__+': '+str(e).replace(str(ROOT),'<checkout>')
finally:
    if server:server.close()
    if proc and proc.poll() is None:proc.terminate();proc.wait(6)
    if os.getuid()==0:os.setgid(501);os.setuid(501)
    r['source']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*sorted((ROOT/'pathquill').glob('*.py')),*sorted((ROOT/'tests').glob('*.py')),ROOT/'tools/milestone1.py',ROOT/'pyproject.toml']}
    out=ROOT/'evidence/milestone1.json';out.write_text(json.dumps(r,indent=2)+'\n');out.with_suffix('.html').write_text('<!doctype html><meta charset="utf-8"><pre>'+html.escape(json.dumps(r,indent=2))+'</pre>')
sys.exit(0 if r['passed'] else 1)
