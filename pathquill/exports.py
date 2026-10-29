"""Durable request/hold/snapshot transactions. No filesystem publication."""
import hashlib
import html
import json
import math
import re
import uuid
from .core import Refused,boottime
from .managed import ManagedRecorder
from .redaction import Redactor

class ExportRecorder(ManagedRecorder):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.db.executescript('CREATE TABLE IF NOT EXISTS exports(request TEXT PRIMARY KEY,source TEXT,params TEXT,state TEXT,token TEXT,boot TEXT,deadline REAL,snapshot TEXT,digest TEXT);')
        with self.db:
            for request,source,token in self.db.execute("SELECT request,source,token FROM exports WHERE state IN ('QUEUED','SNAPSHOTTING')").fetchall():
                held=self.db.execute('SELECT token FROM holds WHERE id=?',(source,)).fetchone()
                if held!=(token,):self.db.execute("UPDATE exports SET state='BLOCKED' WHERE request=?",(request,))
                else:
                    self.db.execute('DELETE FROM holds WHERE id=? AND token=?',(source,token))
                    self.db.execute("UPDATE exports SET state='INTERRUPTED' WHERE request=?",(request,))
    def _owned(self,source,token):
        if self.db.execute('SELECT token FROM holds WHERE id=?',(source,)).fetchone()!=(token,):raise Refused('reference_mismatch')
    def request_export(self,request,source,seconds,epoch):
        self.epoch_check(epoch)
        if not isinstance(request,str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',request):raise Refused('request_id')
        if type(seconds) not in (int,float) or not math.isfinite(seconds) or not .1<=seconds<=60:raise Refused('deadline')
        if not isinstance(source,str):raise Refused('source_id')
        try:uuid.UUID(source)
        except ValueError:raise Refused('source_id')
        seconds=float(seconds)
        params=json.dumps([source,seconds,'pathquill-snapshot-v1'],separators=(',',':'))
        def write():
            old=self.db.execute('SELECT params FROM exports WHERE request=?',(request,)).fetchone()
            if old:
                if old[0]!=params:raise Refused('request_conflict')
                return
            if self.db.execute('SELECT count(*) FROM exports').fetchone()[0]>=32:raise Refused('export_history_full')
            if self.db.execute("SELECT 1 FROM exports WHERE state IN ('QUEUED','SNAPSHOTTING','BLOCKED')").fetchone():raise Refused('export_busy')
            if self.db.execute('SELECT state FROM incidents WHERE id=?',(source,)).fetchone()!=('SEALED',):raise Refused('not_sealed')
            if self.db.execute('SELECT 1 FROM holds WHERE id=?',(source,)).fetchone():raise Refused('reference_busy')
            # Reserve one maximum snapshot before admission, independent of data budget.
            used=self.db.execute('SELECT coalesce(sum(length(CAST(snapshot AS BLOB))),0) FROM exports').fetchone()[0]
            if used+262144>1048576:raise Refused('snapshot_budget')
            token='export:'+str(uuid.uuid4())
            self.db.execute('INSERT INTO holds VALUES(?,?)',(source,token))
            self.db.execute('INSERT INTO exports VALUES(?,?,?,?,?,?,?,NULL,NULL)',(request,source,params,'QUEUED',token,self.boot,boottime()+seconds))
        self.mutation(write);return self.export_status(request)
    def validate_request(self,request):
        if not isinstance(request,str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',request):raise Refused('request_id')
    def export_status(self,request):
        self.validate_request(request)
        row=self.db.execute('SELECT state,deadline,digest FROM exports WHERE request=?',(request,)).fetchone()
        if row is None:raise Refused('request_not_found')
        return dict(request=request,state=row[0],deadline=row[1],digest=row[2])
    def cancel_export(self,request,epoch):
        self.epoch_check(epoch)
        self.validate_request(request)
        def write():
            row=self.db.execute('SELECT state,source,token FROM exports WHERE request=?',(request,)).fetchone()
            if row is None:raise Refused('request_not_found')
            if row[0] in ('CANCELLED','FAILED','EXPIRED','INTERRUPTED'):return
            if row[0]=='BLOCKED':raise Refused('reference_mismatch')
            if row[0] in ('QUEUED','SNAPSHOTTING'):
                self._owned(row[1],row[2]);self.db.execute('DELETE FROM holds WHERE id=? AND token=?',(row[1],row[2]))
            self.db.execute("UPDATE exports SET state='CANCELLED',snapshot=NULL,digest=NULL WHERE request=?",(request,))
        self.mutation(write);return self.export_status(request)
    def advance_exports(self):
        if self.degraded:return
        row=self.db.execute("SELECT request,source,token,boot,deadline,state FROM exports WHERE state IN ('QUEUED','SNAPSHOTTING') LIMIT 1").fetchone()
        if row is None:return
        request,source,token,boot,deadline,state=row
        def write():
            self._owned(source,token)
            if boot!=self.boot or boottime()>=deadline:terminal='EXPIRED'
            elif state=='QUEUED':
                self.db.execute("UPDATE exports SET state='SNAPSHOTTING' WHERE request=?",(request,));return
            else:
                incident=self.db.execute('SELECT state,coverage,reason,recovered,body,first,end FROM incidents WHERE id=?',(source,)).fetchone()
                if incident is None or incident[0]!='SEALED':raise Refused('source_changed')
                count,size=self.db.execute('SELECT count(*),coalesce(sum(length(CAST(body AS BLOB))),0) FROM capture WHERE id=?',(source,)).fetchone()
                if count>4096 or size>1048576:terminal='FAILED'
                else:
                    rows=self.db.execute('SELECT body,t FROM capture WHERE id=? ORDER BY seq',(source,)).fetchall()
                    try:snapshot=Redactor().snapshot(incident,rows)
                    except (ValueError,KeyError,TypeError,OverflowError,AttributeError,UnicodeError):snapshot=None
                    if snapshot is None or len(snapshot.encode())>262144:terminal='FAILED'
                    elif boottime()>=deadline:terminal='EXPIRED'
                    else:
                        self.db.execute("UPDATE exports SET state='SNAPSHOT_READY',snapshot=?,digest=? WHERE request=?",(snapshot,hashlib.sha256(snapshot.encode()).hexdigest(),request));terminal=None
            if terminal:self.db.execute('UPDATE exports SET state=? WHERE request=?',(terminal,request))
            self.db.execute('DELETE FROM holds WHERE id=? AND token=?',(source,token))
        try:self.mutation(write)
        except Refused:
            # Unknown ownership remains protected and blocks further exports.
            with self.db:self.db.execute("UPDATE exports SET state='BLOCKED' WHERE request=?",(request,))
    def read_snapshot(self,request):
        self.validate_request(request)
        row=self.db.execute('SELECT state,snapshot,digest FROM exports WHERE request=?',(request,)).fetchone()
        if row is None or row[0]!='SNAPSHOT_READY':raise Refused('snapshot_not_ready')
        if hashlib.sha256(row[1].encode()).hexdigest()!=row[2]:raise Refused('snapshot_corrupt')
        return dict(snapshot=json.loads(row[1]),digest=row[2],preview_html='<!doctype html><meta charset="utf-8"><pre>'+html.escape(row[1])+'</pre>')
    def hold(self,key,epoch):
        self.epoch_check(epoch)
        held=self.db.execute('SELECT token FROM holds WHERE id=?',(key,)).fetchone()
        if held and held[0].startswith('export:'):raise Refused('export_reference')
        return super().hold(key,epoch)
    def release(self,key,token,epoch):
        self.epoch_check(epoch)
        if isinstance(token,str) and token.startswith('export:'):raise Refused('export_reference')
        return super().release(key,token,epoch)
