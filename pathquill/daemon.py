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
import threading
from .core import Refused,boottime
from .managed import ManagedRecorder
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

def measured_probe(target,started):
    start=boottime();started['at']=start;started['event'].set()
    outcome=tcp(target)
    return outcome,start,boottime()

def accept_result(recorder,health,target,index,outcome,start,end,generation,current):
    if generation!=current:return False
    recorder.observe(dict(kind=target.get('kind','tcp'),target=index,outcome=outcome,generation=generation,start=start,end=end))
    if recorder.degraded:return False
    health[str(index)]=outcome
    if outcome in ('refused','timeout','network_error','dns_error'):
        # Re-read time after FULL commit, which may have crossed the deadline.
        decision=boottime()
        active=recorder.db.execute("SELECT end FROM incidents WHERE state='CAPTURING'").fetchone()
        if active is None or decision<=active[0]:recorder.incident(dict(endpoints=[target['host']]),decision)
    return True

def recovery_ready(health,checked,count,status,first):
    return status=='RECORDING' and count>0 and len(health)==count and all(health.get(str(i))=='success' and checked.get(str(i),-1)>=first for i in range(count))

def serve(root,targets,data_limit=1048576,slots=32,retention=86400):
    r=ManagedRecorder(root,byte_limit=data_limit,slots=slots,retention=retention);backend=RouteSocket();state=State();rpc=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);path=Path(root)/'control.sock'
    path.unlink(missing_ok=True);rpc.bind(str(path));os.chmod(path,0o600);rpc.listen(8);rpc.setblocking(False)
    running=True;health={};checked={};pending={};next_run={i:0 for i in range(len(targets))};stale=0;committed=0;observed=0;results=[]
    def stop(*_):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    pool=concurrent.futures.ThreadPoolExecutor(max_workers=max(1,len(targets)))
    def rebuild():
        health.clear();checked.clear();ok=state.rebuild(backend)
        if ok:
            for group,items in state.view.items():
                for value in items.values():r.observe(dict(kind='state_object',group=group,generation=state.generation,value=value))
        r.observe(dict(kind='sync',generation=state.generation,valid=ok))
        for key, in r.db.execute("SELECT id FROM incidents WHERE state='CAPTURING'").fetchall():r.gap(key,'resynchronize')
    try:
        rebuild();last_retry=boottime();last_gc=boottime()
        while running:
            # Drain currently available notifications before committing a progress barrier.
            reads,_,_=select.select([backend.socket,rpc],[],[],.02)
            if backend.socket in reads:
                try:
                    messages=backend.receive();observed+=len(messages)
                    for message in messages:r.observe(dict(kind='notification',type=message['kind']))
                    rebuild()
                except (OSError,ValueError,BufferError):
                    state.invalidate('receive_error');health.clear();checked.clear()
                    r.observe(dict(kind='gap',reason='receive_error'))
                    for key, in r.db.execute("SELECT id FROM incidents WHERE state='CAPTURING'").fetchall():r.gap(key,'receive_error')
            if rpc in reads:
                conn,_=rpc.accept();conn.settimeout(.2)
                with conn:
                    try:
                        data=conn.recv(4097)
                        if len(data)>4096:raise ValueError('request_size')
                        request=json.loads(data)
                        if not isinstance(request,dict):raise ValueError('request_type')
                        if request.get('op')=='resync':rebuild()
                        elif request.get('op')=='gc':r.collect(request.get('epoch'))
                        elif request.get('op')=='delete':r.remove(request.get('id'),request.get('epoch'))
                        elif request.get('op')=='hold':r.hold(request.get('id'),request.get('epoch'))
                        elif request.get('op')=='release':r.release(request.get('id'),request.get('token'),request.get('epoch'))
                        elif request.get('op')!='status':raise ValueError('unknown_operation')
                        incidents=[dict(id=x[0],state=x[1],coverage=x[2],recovered=bool(x[3])) for x in r.db.execute('SELECT id,state,coverage,recovered FROM incidents')]
                        reply=dict(ok=True,capacity=r.usage(),epoch=r.epoch,generation=state.generation,state=state.status,view=state.view,health=health,health_probe_started=checked,stale_results=stale,gaps=state.gaps,committed=committed,notifications=observed,incidents=incidents,pending=[dict(target=i,generation=p[1],started=p[2].get('at') if p[2]['event'].is_set() else None,done=p[0].done()) for i,p in pending.items()],results=results)
                        conn.sendall(json.dumps(reply).encode())
                    except Refused as error:
                        try:conn.sendall(json.dumps(dict(ok=False,error=str(error))).encode())
                        except OSError:pass
                    except (OSError,ValueError):pass
            now=boottime()
            if r.degraded and state.status!='STORAGE_ERROR':
                state.invalidate('storage_error');state.status='STORAGE_ERROR';health.clear();checked.clear()
            if not r.degraded and state.status!='RECORDING' and now-last_retry>=1:
                rebuild();last_retry=boottime();last_gc=boottime()
            for i,(future,generation,started) in list(pending.items()):
                if not future.done():continue
                del pending[i];next_run[i]=now+targets[i]['interval']
                outcome,start,end=future.result()
                results=(results+[dict(target=i,generation=generation,outcome=outcome,start=start,end=end,stale=generation!=state.generation)])[-16:]
                if not accept_result(r,health,targets[i],i,outcome,start,end,generation,state.generation):
                    stale+=int(generation!=state.generation);continue
                checked[str(i)]=start
            if not r.degraded and now-last_gc>=1:
                r.collect(r.epoch);last_gc=now
            # Same thread owns receive, writes and this commit: no pending writer queue.
            if not select.select([backend.socket],[],[],0)[0]:
                r.observe(dict(kind='progress',generation=state.generation));committed=r.db.execute('SELECT max(seq) FROM observations').fetchone()[0]
                for key,first,end in r.db.execute("SELECT id,first,end FROM incidents WHERE state='CAPTURING'").fetchall():
                    if now>=end and not pending:
                        recovered=recovery_ready(health,checked,len(targets),state.status,first)
                        # This watermark comes only from the successfully committed progress record.
                        r.finish(key,boottime(),r.epoch,r.watermark,recovered)
            expired=r.db.execute("SELECT 1 FROM incidents WHERE state='CAPTURING' AND end<=?",(now,)).fetchone()
            for i,target in enumerate(targets):
                if not r.degraded and not expired and state.status=='RECORDING' and i not in pending and now>=next_run[i]:
                    started=dict(event=threading.Event());pending[i]=(pool.submit(measured_probe,target,started),state.generation,started)
    finally:
        pool.shutdown(wait=True,cancel_futures=True);backend.close();rpc.close();path.unlink(missing_ok=True);r.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--config',required=True);p.add_argument('--data-bytes',type=int,default=1048576);p.add_argument('--slots',type=int,default=32);p.add_argument('--retention-seconds',type=float,default=86400);a=p.parse_args()
    if not 128<=a.data_bytes<=67108864 or not 1<=a.slots<=32 or not .1<=a.retention_seconds<=86400:raise ValueError('resource_limits')
    if Path(a.config).stat().st_size>16384:raise ValueError('configuration_budget')
    targets=json.loads(Path(a.config).read_text())
    if not isinstance(targets,list) or len(targets)>8:raise ValueError('target_budget')
    for target in targets:
        address=ipaddress.ip_address(target['host'])
        if target.get('kind','tcp') not in ('tcp','dns') or (target.get('kind')=='dns' and address.version!=4):raise ValueError('probe_kind_or_family')
        if not 1<=target['port']<=65535 or not .05<=target['timeout']<=2 or not .1<=target['interval']<=60:raise ValueError('target_limits')
    serve(a.root,targets,a.data_bytes,a.slots,a.retention_seconds)
if __name__=='__main__':main()
