"""Minimal durable incident core. All mutation belongs to one lock owner."""
import fcntl
import hashlib
import html
import ipaddress
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

class Refused(RuntimeError):pass

def boottime():
    return time.clock_gettime(time.CLOCK_BOOTTIME)

class Inbox:
    def __init__(self,count=4096,bytes_limit=1048576,item_limit=4096):
        self.count=count;self.limit=bytes_limit;self.item=item_limit;self.queue=[];self.bytes=0;self.dropped=0
    def put(self,event):
        n=len(json.dumps(event).encode())
        if n>self.item or len(self.queue)>=self.count or self.bytes+n>self.limit:
            self.dropped+=1;return False
        self.queue.append((event,n));self.bytes+=n;return True
    def drain(self):
        result=[v for v,n in self.queue];self.queue=[];self.bytes=0
        loss=self.dropped;self.dropped=0;return result,loss

class Store:
    def __init__(self,root,slots=32,byte_limit=1048576):
        self.root=Path(root);self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        st=self.root.lstat()
        if self.root.is_symlink() or st.st_uid!=os.getuid() or st.st_mode&0o077:raise Refused('private_owned_directory_required')
        self.lock=open(self.root/'writer.lock','a')
        try:fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:self.lock.close();raise Refused('writer_busy')
        os.chmod(self.root/'writer.lock',0o600)
        self.db=sqlite3.connect(self.root/'state.db',timeout=.1)
        os.chmod(self.root/'state.db',0o600)
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone() and self.db.execute("SELECT value FROM meta WHERE key='lifecycle'").fetchone()==('SEALED',):
            self.db.close();fcntl.flock(self.lock,fcntl.LOCK_UN);self.lock.close();raise Refused('store_sealed')
        self.db.execute('PRAGMA journal_mode=DELETE');self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY, first REAL,end REAL,state TEXT,coverage TEXT,reason TEXT,recovered INTEGER,body TEXT); CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);')
        self.sealed=False
        self.epoch=str(uuid.uuid4());self.slots=slots;self.limit=byte_limit;self.degraded=False
        with self.db:
            self.db.execute("UPDATE incidents SET state='SEALED',coverage='PARTIAL',reason='restart' WHERE state='CAPTURING'")
            self.db.execute("INSERT OR REPLACE INTO meta VALUES('epoch',?)",(self.epoch,))
            self.db.execute("INSERT OR IGNORE INTO meta VALUES('store_id',?)",(str(uuid.uuid4()),))
            self.db.execute("INSERT OR IGNORE INTO meta VALUES('lifecycle','OPEN')")
        self.store_id=self.db.execute("SELECT value FROM meta WHERE key='store_id'").fetchone()[0]
    def close(self):self.db.close();fcntl.flock(self.lock,fcntl.LOCK_UN);self.lock.close()
    def trigger(self,now,payload):
        if self.degraded:raise Refused('storage_degraded')
        body=json.dumps(payload,allow_nan=False)
        if len(body.encode())>4096:raise Refused('event_too_large')
        row=self.db.execute("SELECT id,first,end FROM incidents WHERE state='CAPTURING'").fetchone()
        if row:
            with self.db:self.db.execute('UPDATE incidents SET end=? WHERE id=?',(min(row[1]+120,max(row[2],now+30)),row[0]))
            return row[0]
        count,used=self.db.execute('SELECT count(*),coalesce(sum(length(CAST(body AS BLOB))),0) FROM incidents').fetchone()
        if count>=self.slots or used+len(body.encode())>self.limit:raise Refused('capacity_busy')
        key=str(uuid.uuid4())
        try:
            with self.db:self.db.execute('INSERT INTO incidents VALUES(?,?,?,?,?,?,?,?)',(key,now,now+30,'CAPTURING','UNKNOWN','capturing',0,body))
        except sqlite3.Error:self.degraded=True;raise
        return key
    def gap(self,key,reason):
        with self.db:self.db.execute("UPDATE incidents SET coverage='PARTIAL',reason=? WHERE id=? AND state='CAPTURING'",(reason,key))
    def finish(self,key,now,epoch,watermark,recovered=False):
        if epoch!=self.epoch:raise Refused('stale_epoch')
        row=self.db.execute('SELECT end,state FROM incidents WHERE id=?',(key,)).fetchone()
        if not row or row[1]!='CAPTURING':raise Refused('not_capturing')
        if now<row[0] or watermark<row[0]:raise Refused('window_not_drained')
        with self.db:self.db.execute("UPDATE incidents SET state='SEALED',reason='window_end',recovered=? WHERE id=?",(int(recovered),key))
    def delete(self,key):
        with self.db:
            row=self.db.execute('SELECT state FROM incidents WHERE id=?',(key,)).fetchone()
            if row and row[0]=='CAPTURING':raise Refused('capture_busy')
            self.db.execute('DELETE FROM incidents WHERE id=?',(key,))
    def export(self,key):
        row=self.db.execute('SELECT state,coverage,reason,recovered,body FROM incidents WHERE id=?',(key,)).fetchone()
        if not row or row[0]!='SEALED':raise Refused('not_sealed')
        # Explicit allowlist: no free text, paths, addresses or raw identifiers.
        raw=json.loads(row[4]);mapping={}
        def alias(value):
            try:value=str(ipaddress.ip_address(value))
            except ValueError:value=value.rstrip('.').lower()
            if value not in mapping:mapping[value]='endpoint_'+str(len(mapping)+1)
            return mapping[value]
        result=dict(state=row[0],coverage=row[1],recovered=bool(row[3]),end_reason=row[2] if row[2] in ('restart','window_end') else 'observation_gap',endpoints=[alias(v) for v in raw.get('endpoints',[])])
        data=json.dumps(result,sort_keys=True,allow_nan=False)
        return dict(json=data,html='<!doctype html><meta charset="utf-8"><pre>'+html.escape(data)+'</pre>',sha256=hashlib.sha256(data.encode()).hexdigest())

class Observer:
    def __init__(self):self.generation=0;self.state='SYNCING';self.gaps=[];self.health={}
    def lost(self,reason,count=None):
        self.gaps.append(dict(reason=reason,lost_count=count));self.generation+=1;self.state='DEGRADED';self.health={}
    def synchronized(self,valid):self.state='RECORDING' if valid else 'DEGRADED'
    def result(self,target,family,generation,ok):
        if generation!=self.generation:raise Refused('stale_probe')
        self.health[(target,family)]=ok
