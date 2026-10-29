"""Bounded control records, conservative retention and transactional reclamation."""
import json
import os
import sqlite3
import uuid
from .core import Refused,boottime
from .recorder import Recorder

class ManagedRecorder(Recorder):
    def __init__(self,*args,retention=86400,**kwargs):
        super().__init__(*args,**kwargs)
        self.retention=retention;self.ring_limit=max(1,self.limit//4)
        self.db.executescript('CREATE TABLE IF NOT EXISTS control(id INTEGER PRIMARY KEY CHECK(id=1),loss INTEGER,refusals INTEGER,progress REAL,mode TEXT); INSERT OR IGNORE INTO control VALUES(1,0,0,0,"OK"); CREATE TABLE IF NOT EXISTS lifetime(id TEXT PRIMARY KEY,boot TEXT,sealed REAL,retention REAL); CREATE TABLE IF NOT EXISTS holds(id TEXT PRIMARY KEY,token TEXT UNIQUE);')
        # Missing metadata or a new boot can only extend retention, never shorten it.
        with self.db:
            for key,state in self.db.execute('SELECT id,state FROM incidents').fetchall():
                old=self.db.execute('SELECT boot,sealed,retention FROM lifetime WHERE id=?',(key,)).fetchone()
                if old is None or (state=='SEALED' and (old[0]!=self.boot or old[1] is None)):
                    self.db.execute('INSERT OR REPLACE INTO lifetime VALUES(?,?,?,?)',(key,self.boot,boottime() if state=='SEALED' else None,old[2] if old else 86400))
            self.db.execute('UPDATE control SET mode="OK",progress=0 WHERE id=1')
    def storage_error(self):self.degraded=True
    def control_write(self,loss=0,refusal=0,progress=None):
        if self.degraded:return False
        try:
            with self.db:
                self.db.execute('UPDATE control SET loss=min(loss+?,9223372036854775807),refusals=min(refusals+?,9223372036854775807),mode="CAPACITY" WHERE id=1',(loss,refusal))
                self.db.execute("UPDATE incidents SET coverage='PARTIAL',reason='capacity_gap' WHERE state='CAPTURING'")
                if progress is not None:self.db.execute('UPDATE control SET progress=? WHERE id=1',(progress,))
            if progress is not None:self.watermark=progress
            return True
        except (sqlite3.Error,OSError):self.storage_error();return False
    def observe(self,event,now=None):
        if self.degraded:return None
        try:
            size=len(json.dumps(event,allow_nan=False).encode())
            if size>self.ring_limit:raise Refused('observation_capacity')
            with self.db:
                used=self.db.execute('SELECT coalesce(sum(length(CAST(body AS BLOB))),0) FROM observations').fetchone()[0]
                while used+size>self.ring_limit:
                    row=self.db.execute('SELECT seq,length(CAST(body AS BLOB)) FROM observations ORDER BY seq LIMIT 1').fetchone()
                    self.db.execute('DELETE FROM observations WHERE seq=?',(row[0],));used-=row[1]
            seq=super().observe(event,now)
            if event.get('kind')=='progress':
                with self.db:self.db.execute('UPDATE control SET progress=?,mode="OK" WHERE id=1',(self.watermark,))
            return seq
        except Refused as e:
            if str(e) not in ('observation_capacity','event_too_large'):raise
            self.control_write(loss=1,progress=(boottime() if now is None else now) if event.get('kind')=='progress' else None)
            return None
        except (sqlite3.Error,OSError):self.storage_error();return None
    def incident(self,payload,now=None):
        if self.degraded:return None
        try:
            key=super().incident(payload,now)
            with self.db:self.db.execute('INSERT OR IGNORE INTO lifetime VALUES(?,?,NULL,?)',(key,self.boot,self.retention))
            return key
        except Refused as e:
            if str(e) not in ('capacity_busy','capture_capacity','event_too_large'):raise
            self.control_write(refusal=1);return None
        except (sqlite3.Error,OSError):self.storage_error();return None
    def finish(self,key,now,epoch,watermark,recovered=False):
        if self.degraded:return False
        try:
            super().finish(key,now,epoch,watermark,recovered)
            with self.db:self.db.execute('INSERT OR REPLACE INTO lifetime VALUES(?,?,?,?)',(key,self.boot,boottime(),self.retention))
            return True
        except (sqlite3.Error,OSError):self.storage_error();return False
    def gap(self,key,reason):
        if self.degraded:return
        try:super().gap(key,reason)
        except (sqlite3.Error,OSError):self.storage_error()
    def epoch_check(self,epoch):
        if epoch!=self.epoch:raise Refused('stale_epoch')
        if self.degraded:raise Refused('storage_degraded')
        if self.sealed:raise Refused('store_sealed')
    def hold(self,key,epoch):
        self.epoch_check(epoch)
        def write():
            row=self.db.execute('SELECT state FROM incidents WHERE id=?',(key,)).fetchone()
            if row is None or row[0]!='SEALED':raise Refused('not_sealed')
            old=self.db.execute('SELECT token FROM holds WHERE id=?',(key,)).fetchone()
            if old:return old[0]
            token=str(uuid.uuid4());self.db.execute('INSERT INTO holds VALUES(?,?)',(key,token));return token
        return self.mutation(write)
    def release(self,key,token,epoch):
        self.epoch_check(epoch)
        def write():
            if self.db.execute('SELECT token FROM holds WHERE id=?',(key,)).fetchone()!=(token,):raise Refused('reference_mismatch')
            self.db.execute('DELETE FROM holds WHERE id=?',(key,))
        self.mutation(write)
    def remove(self,key,epoch):
        self.epoch_check(epoch)
        def write():
            row=self.db.execute('SELECT state FROM incidents WHERE id=?',(key,)).fetchone()
            if row is None:raise Refused('not_found')
            if row[0]!='SEALED':raise Refused('capture_busy')
            if self.db.execute('SELECT 1 FROM holds WHERE id=?',(key,)).fetchone():raise Refused('reference_busy')
            self.db.execute('DELETE FROM capture WHERE id=?',(key,));self.db.execute('DELETE FROM incidents WHERE id=?',(key,));self.db.execute('DELETE FROM lifetime WHERE id=?',(key,))
        self.mutation(write)
    def collect(self,epoch,now=None):
        self.epoch_check(epoch);now=boottime() if now is None else now
        def write():
            rows=self.db.execute("SELECT i.id FROM incidents i JOIN lifetime l ON i.id=l.id WHERE i.state='SEALED' AND l.boot=? AND l.sealed IS NOT NULL AND l.sealed+l.retention<=? AND NOT EXISTS(SELECT 1 FROM holds h WHERE h.id=i.id)",(self.boot,now)).fetchall()
            for key, in rows:
                self.db.execute('DELETE FROM capture WHERE id=?',(key,));self.db.execute('DELETE FROM incidents WHERE id=?',(key,));self.db.execute('DELETE FROM lifetime WHERE id=?',(key,))
            return [key for key, in rows]
        return self.mutation(write)
    def usage(self):
        control=self.db.execute('SELECT loss,refusals,progress,mode FROM control WHERE id=1').fetchone()
        return dict(loss=control[0],refusals=control[1],progress=control[2],mode='STORAGE_ERROR' if self.degraded else control[3],logical_bytes=sum(self.db.execute('SELECT coalesce(sum(length(CAST(body AS BLOB))),0) FROM '+table).fetchone()[0] for table in ('incidents','observations','capture')),data_limit=self.limit,prebuffer_oldest=self.db.execute('SELECT min(t) FROM observations').fetchone()[0],prebuffer_latest=self.db.execute('SELECT max(t) FROM observations').fetchone()[0],ring_limit=self.ring_limit,incidents=self.db.execute('SELECT count(*) FROM incidents').fetchone()[0],holds=[dict(id=x[0],token=x[1]) for x in self.db.execute('SELECT id,token FROM holds')],filesystem_bytes=sum(p.stat().st_size for p in self.root.iterdir() if p.is_file()),free_pages=self.db.execute('PRAGMA freelist_count').fetchone()[0])
    def reclaim(self,key):return self.remove(key,self.epoch)
    def delete(self,key):return self.remove(key,self.epoch)
    def trigger(self,now,payload):return self.incident(payload,now)
