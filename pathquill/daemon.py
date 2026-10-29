"""Single writer daemon; network workers return data only, never mutate SQLite."""
import argparse
import concurrent.futures
import errno
import ipaddress
import json
import os
from pathlib import Path
import select
import signal
import socket
import time
from .core import Refused,boottime
from .recorder import Recorder
from .netlink import RouteSocket
from .state import State
from .probes import dns_query

def tcp(target):
    if target.get('kind','tcp')=='dns':return dns_query(target['host'],target['port'],target['timeout'])
    family=socket.AF_INET6 if ipaddress.ip_address(target['host']).version==6 else socket.AF_INET
    outcome='success'
    try:
        with socket.socket(family,socket.SOCK_STREAM) as s:s.settimeout(target['timeout']);s.connect((target['host'],target['port']))
    except socket.timeout:outcome='timeout'
    except OSError as e:outcome='refused' if e.errno==errno.ECONNREFUSED else 'network_error'
    return outcome

def serve(root,targets):
    r=Recorder(root);backend=RouteSocket();state=State();rpc=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);path=Path(root)/'control.sock'
    path.unlink(missing_ok=True);rpc.bind(str(path));os.chmod(path,0o600);rpc.listen(8);rpc.setblocking(False)
    running=True;health={};pending={};next_run={i:0 for i in range(len(targets))};stale=0;committed=0;observed=0
    def stop(*_):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    pool=concurrent.futures.ThreadPoolExecutor(max_workers=max(1,len(targets)))
    def rebuild():
        health.clear();ok=state.rebuild(backend)
        if ok:
            for group,items in state.view.items():
                for value in items.values():r.observe(dict(kind='state_object',group=group,generation=state.generation,value=value))
        r.observe(dict(kind='sync',generation=state.generation,valid=ok))
        for key, in r.db.execute("SELECT id FROM incidents WHERE state='CAPTURING'").fetchall():r.gap(key,'resynchronize')
    try:
        rebuild();last_retry=boottime()
        while running:
            # Drain currently available notifications before committing a progress barrier.
            reads,_,_=select.select([backend.socket,rpc],[],[],.02)
            if backend.socket in reads:
                try:
                    messages=backend.receive();observed+=len(messages)
                    for message in messages:r.observe(dict(kind='notification',type=message['kind']))
                    rebuild()
                except (OSError,ValueError,BufferError):
                    state.invalidate('receive_error');health.clear()
                    r.observe(dict(kind='gap',reason='receive_error'))
                    for key, in r.db.execute("SELECT id FROM incidents WHERE state='CAPTURING'").fetchall():r.gap(key,'receive_error')
            if rpc in reads:
                conn,_=rpc.accept();conn.settimeout(.2)
                with conn:
                    try:
                        data=conn.recv(4097)
                        if len(data)>4096:raise ValueError('request_size')
                        request=json.loads(data)
                        if request.get('op')=='resync':rebuild()
                        elif request.get('op')!='status':raise ValueError('unknown_operation')
                        incidents=[dict(id=x[0],state=x[1],coverage=x[2],recovered=bool(x[3])) for x in r.db.execute('SELECT id,state,coverage,recovered FROM incidents')]
                        reply=dict(ok=True,epoch=r.epoch,generation=state.generation,state=state.status,view=state.view,health=health,stale_results=stale,gaps=state.gaps,committed=committed,notifications=observed,incidents=incidents)
                        conn.sendall(json.dumps(reply).encode())
                    except (OSError,ValueError):pass
            now=boottime()
            if state.status!='RECORDING' and now-last_retry>=1:
                rebuild();last_retry=boottime()
            for i,(future,generation) in list(pending.items()):
                if not future.done():continue
                del pending[i];next_run[i]=now+targets[i]['interval']
                if generation!=state.generation:stale+=1;continue
                outcome=future.result();r.observe(dict(kind='tcp',target=i,outcome=outcome,generation=generation))
                health[str(i)]=outcome
                if outcome in ('refused','timeout','network_error','dns_error'):
                    # Ended captures are finalized by the progress barrier below.
                    active=r.db.execute("SELECT end FROM incidents WHERE state='CAPTURING'").fetchone()
                    if active is None or now<=active[0]:r.incident(dict(endpoints=[targets[i]['host']]))
            # Same thread owns receive, writes and this commit: no pending writer queue.
            if not select.select([backend.socket],[],[],0)[0]:
                r.observe(dict(kind='progress',generation=state.generation));committed=r.db.execute('SELECT max(seq) FROM observations').fetchone()[0]
                for key,end in r.db.execute("SELECT id,end FROM incidents WHERE state='CAPTURING'").fetchall():
                    if now>=end and not pending:
                        recovered=state.status=='RECORDING' and len(health)==len(targets) and bool(targets) and all(x=='success' for x in health.values())
                        # This watermark comes only from the successfully committed progress record.
                        r.finish(key,boottime(),r.epoch,r.watermark,recovered)
            expired=r.db.execute("SELECT 1 FROM incidents WHERE state='CAPTURING' AND end<=?",(now,)).fetchone()
            for i,target in enumerate(targets):
                if not expired and state.status=='RECORDING' and i not in pending and now>=next_run[i]:pending[i]=(pool.submit(tcp,target),state.generation)
    finally:
        pool.shutdown(wait=True,cancel_futures=True);backend.close();rpc.close();path.unlink(missing_ok=True);r.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--config',required=True);a=p.parse_args()
    if Path(a.config).stat().st_size>16384:raise ValueError('configuration_budget')
    targets=json.loads(Path(a.config).read_text())
    if not isinstance(targets,list) or len(targets)>8:raise ValueError('target_budget')
    for target in targets:
        address=ipaddress.ip_address(target['host'])
        if target.get('kind','tcp') not in ('tcp','dns') or (target.get('kind')=='dns' and address.version!=4):raise ValueError('probe_kind_or_family')
        if not 1<=target['port']<=65535 or not .05<=target['timeout']<=2 or not .1<=target['interval']<=60:raise ValueError('target_limits')
    serve(a.root,targets)
if __name__=='__main__':main()
