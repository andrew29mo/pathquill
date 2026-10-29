"""Persistent observation ring and real probe-to-incident integration."""
import errno
import json
import socket
import struct
import time
from .core import Store,Refused,boottime

class Recorder(Store):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.boot=open('/proc/sys/kernel/random/boot_id').read().strip()
        self.db.executescript('CREATE TABLE IF NOT EXISTS observations(seq INTEGER PRIMARY KEY AUTOINCREMENT,boot TEXT,epoch TEXT,t REAL,body TEXT); CREATE TABLE IF NOT EXISTS capture(id TEXT,seq INTEGER,body TEXT,PRIMARY KEY(id,seq));')
        self.watermark=0
    def mutation(self,fn):
        if self.degraded:raise Refused('storage_degraded')
        try:
            with self.db:return fn()
        except (OSError, __import__('sqlite3').Error):self.degraded=True;raise
    def observe(self,event,now=None):
        now=boottime() if now is None else now
        body=json.dumps(event,allow_nan=False)
        if len(body.encode())>4096:raise Refused('event_too_large')
        def write():
            self.db.execute('DELETE FROM observations WHERE epoch<>? OR t<?',(self.epoch,now-60))
            used=self.db.execute('SELECT coalesce(sum(length(CAST(body AS BLOB))),0) FROM observations').fetchone()[0]+self.db.execute('SELECT coalesce(sum(length(CAST(body AS BLOB))),0) FROM capture').fetchone()[0]
            active=self.db.execute("SELECT id FROM incidents WHERE state='CAPTURING' AND end>=?",(now,)).fetchall()
            if used+len(body.encode())*(1+len(active))>self.limit:raise Refused('observation_capacity')
            seq=self.db.execute('INSERT INTO observations(boot,epoch,t,body) VALUES(?,?,?,?)',(self.boot,self.epoch,now,body)).lastrowid
            for key, in active:self.db.execute('INSERT INTO capture VALUES(?,?,?)',(key,seq,body))
            return seq
        seq=self.mutation(write);self.watermark=now;return seq
    def incident(self,payload,now=None):
        now=boottime() if now is None else now
        def write():
            active=self.db.execute("SELECT id,first,end FROM incidents WHERE state='CAPTURING'").fetchone()
            body=json.dumps(payload,allow_nan=False)
            if len(body.encode())>4096:raise Refused('event_too_large')
            if active:
                key=active[0]
                self.db.execute('UPDATE incidents SET end=? WHERE id=?',(min(active[1]+120,max(active[2],now+30)),key))
            else:
                if self.db.execute('SELECT count(*) FROM incidents').fetchone()[0]>=self.slots:raise Refused('capacity_busy')
                key=str(__import__('uuid').uuid4())
                self.db.execute('INSERT INTO incidents VALUES(?,?,?,?,?,?,?,?)',(key,now,now+30,'CAPTURING','UNKNOWN','capturing',0,body))
            rows=self.db.execute('SELECT seq,body FROM observations WHERE epoch=? AND t>=? AND t<=?',(self.epoch,now-60,now)).fetchall()
            used=self.db.execute('SELECT coalesce(sum(length(CAST(body AS BLOB))),0) FROM capture').fetchone()[0]+self.db.execute('SELECT coalesce(sum(length(CAST(body AS BLOB))),0) FROM observations').fetchone()[0]
            existing={x[0] for x in self.db.execute('SELECT seq FROM capture WHERE id=?',(key,))}
            extra=sum(len(body.encode()) for seq,body in rows if seq not in existing)
            if used+extra>self.limit:raise Refused('capture_capacity')
            for seq,body in rows:self.db.execute('INSERT OR IGNORE INTO capture VALUES(?,?,?)',(key,seq,body))
            return key
        return self.mutation(write)
    def probe(self,host,port,family=socket.AF_INET,timeout=.3):
        start=boottime();outcome='success'
        try:
            with socket.socket(family,socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout);sock.connect((host,port))
        except socket.timeout:outcome='timeout'
        except OSError as exc:outcome='refused' if exc.errno==errno.ECONNREFUSED else 'network_error'
        end=boottime();self.observe(dict(kind='tcp',family=family,outcome=outcome,start=start,end=end))
        if outcome!='success':self.incident(dict(endpoints=[host]),end)
        return outcome
    def dns(self,server,port=53,timeout=.3):
        # One-question explicit UDP DNS probe, no system resolver or hidden retry.
        ident=__import__('secrets').randbelow(65536);name=b'\x07example\x04test\x00'
        query=struct.pack('!HHHHHH',ident,0x100,1,0,0,0)+name+struct.pack('!HH',1,1)
        outcome='success'
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
                sock.settimeout(timeout);sock.connect((server,port));sock.send(query);data=sock.recv(4096)
            if len(data)<12:raise ValueError('short_dns')
            rid,flags,qd,an,ns,ar=struct.unpack('!HHHHHH',data[:12])
            if rid!=ident or not flags&0x8000 or flags&0x200 or qd!=1 or data[12:12+len(query)-12]!=query[12:]:raise ValueError('invalid_dns')
            outcome='success' if flags&15==0 else 'dns_error'
        except (OSError,ValueError):outcome='unknown'
        now=boottime();self.observe(dict(kind='dns',outcome=outcome))
        if outcome=='dns_error':self.incident(dict(endpoints=[server]),now)
        return outcome
    def reclaim(self,key):
        def write():
            row=self.db.execute('SELECT state FROM incidents WHERE id=?',(key,)).fetchone()
            if row and row[0]=='CAPTURING':raise Refused('capture_busy')
            self.db.execute('DELETE FROM capture WHERE id=?',(key,));self.db.execute('DELETE FROM incidents WHERE id=?',(key,))
        self.mutation(write)
