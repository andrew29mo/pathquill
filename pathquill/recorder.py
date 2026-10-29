"""Persistent observation ring and real probe-to-incident integration."""
import errno
import ipaddress
import json
import socket
import struct
import time
from .core import Store,Refused,boottime

class Recorder(Store):
    def __init__(self,*args,**kwargs):
        with open('/proc/sys/kernel/random/boot_id') as boot:self.boot=boot.read().strip()
        super().__init__(*args,**kwargs)
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
            self.db.execute('DELETE FROM observations WHERE boot<>? OR t<?',(self.boot,now-60))
            used=self.db.execute('SELECT coalesce(sum(length(CAST(body AS BLOB))),0) FROM observations').fetchone()[0]+self.db.execute('SELECT coalesce(sum(length(CAST(body AS BLOB))),0) FROM capture').fetchone()[0]+self.db.execute('SELECT coalesce(sum(length(CAST(body AS BLOB))),0) FROM incidents').fetchone()[0]
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
                if now>active[2]:raise Refused('window_expired')
                key=active[0]
                self.db.execute('UPDATE incidents SET end=? WHERE id=?',(min(active[1]+120,max(active[2],now+30)),key))
            else:
                if self.db.execute('SELECT count(*) FROM incidents').fetchone()[0]>=self.slots:raise Refused('capacity_busy')
                key=str(__import__('uuid').uuid4())
                self.db.execute('INSERT INTO incidents VALUES(?,?,?,?,?,?,?,?)',(key,now,now+30,'CAPTURING','UNKNOWN','capturing',0,body))
            rows=self.db.execute('SELECT seq,body FROM observations WHERE boot=? AND t>=? AND t<=?',(self.boot,(active[1] if active else now)-60,now)).fetchall()
            used=self.db.execute('SELECT coalesce(sum(length(CAST(body AS BLOB))),0) FROM capture').fetchone()[0]+self.db.execute('SELECT coalesce(sum(length(CAST(body AS BLOB))),0) FROM incidents').fetchone()[0]+self.db.execute('SELECT coalesce(sum(length(CAST(body AS BLOB))),0) FROM observations').fetchone()[0]
            existing={x[0] for x in self.db.execute('SELECT seq FROM capture WHERE id=?',(key,))}
            extra=sum(len(body.encode()) for seq,body in rows if seq not in existing)
            if used+extra>self.limit:raise Refused('capture_capacity')
            for seq,body in rows:self.db.execute('INSERT OR IGNORE INTO capture VALUES(?,?,?)',(key,seq,body))
            return key
        return self.mutation(write)
    def probe(self,host,port,family=socket.AF_INET,timeout=.3):
        address=ipaddress.ip_address(host)
        if (address.version==4)!=(family==socket.AF_INET):raise ValueError('address_family')
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
        from .probes import dns_query
        outcome=dns_query(server,port,timeout)
        now=boottime();self.observe(dict(kind='dns',outcome=outcome))
        if outcome=='dns_error':self.incident(dict(endpoints=[server]),now)
        return outcome
    def reclaim(self,key):
        def write():
            row=self.db.execute('SELECT state FROM incidents WHERE id=?',(key,)).fetchone()
            if row and row[0]=='CAPTURING':raise Refused('capture_busy')
            self.db.execute('DELETE FROM capture WHERE id=?',(key,));self.db.execute('DELETE FROM incidents WHERE id=?',(key,))
        self.mutation(write)

    def delete(self,key):return self.reclaim(key)
