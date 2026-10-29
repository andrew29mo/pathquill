"""Linux-only, no-replace package publication under the existing writer lock."""
import ctypes
import errno
import hashlib
import html
import json
import os
import re
import stat
import sys
import uuid
from .core import Refused,boottime
from .exports import ExportRecorder

PACKAGE_LIMIT=2097152
FILE_BUDGET=4194304

def rename_new(source,destination):
    # Unlike os.rename, RENAME_NOREPLACE also refuses an existing empty directory.
    if sys.platform!='linux':raise OSError(errno.ENOTSUP,'unsupported platform')
    libc=ctypes.CDLL(None,use_errno=True)
    fn=getattr(libc,'renameat2',None)
    if fn is None:raise OSError(errno.ENOTSUP,'renameat2 unavailable')
    fn.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];fn.restype=ctypes.c_int
    if fn(-100,os.fsencode(source),-100,os.fsencode(destination),1):
        code=ctypes.get_errno();raise OSError(code,'package rename refused')

def sync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

def package_bodies(snapshot):
    bodies={'snapshot.json':snapshot.encode(),'index.html':('<!doctype html><meta charset="utf-8"><pre>'+html.escape(snapshot)+'</pre>').encode()}
    manifest=dict(schema='pathquill-package-v1',files={name:dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest()) for name,data in bodies.items()})
    bodies['manifest.json']=json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()
    return bodies

class PublicationRecorder(ExportRecorder):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.db.execute('CREATE TABLE IF NOT EXISTS publications(request TEXT PRIMARY KEY,package TEXT UNIQUE,state TEXT,bytes INTEGER,digest TEXT)')
        columns={row[1] for row in self.db.execute('PRAGMA table_info(publications)')}
        for name,kind in [('stage_dev','INTEGER'),('stage_ino','INTEGER'),('cleanup','TEXT'),('outcome','TEXT'),('delivered','INTEGER DEFAULT 0')]:
            if name not in columns:self.db.execute('ALTER TABLE publications ADD COLUMN '+name+' '+kind)
        with self.db:self.db.execute("UPDATE publications SET delivered=1 WHERE state='PUBLISHED'")
        for request, in self.db.execute('SELECT request FROM publications').fetchall():self.reconcile_publication(request)
    def publication_status(self,request):
        self.validate_request(request)
        row=self.db.execute('SELECT package,state,bytes,digest,outcome FROM publications WHERE request=?',(request,)).fetchone()
        if row is None:raise Refused('publication_not_found')
        return dict(package=row[0],state=row[1],bytes=row[2],digest=row[3],outcome=row[4])
    def cancel_export(self,request,epoch):
        self.epoch_check(epoch);self.validate_request(request)
        row=self.db.execute('SELECT state FROM publications WHERE request=?',(request,)).fetchone()
        if row is not None:
            self.reconcile_publication(request,cancel=True)
            state=self.publication_status(request)['state']
            if state=='PUBLISHED':raise Refused('already_published')
            if state=='BLOCKED':raise Refused('publication_requires_reconciliation')
            return self.publication_status(request)
        return super().cancel_export(request,epoch)
    def package_directory(self):
        directory=self.root/'packages'
        try:directory.mkdir(mode=0o700)
        except FileExistsError:pass
        info=directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise Refused('private_package_directory_required')
        return directory
    def disk_usage(self,directory):
        total=0
        entries=list(directory.iterdir())
        if len(entries)>32:raise Refused('package_entry_budget')
        for entry in entries:
            if not stat.S_ISDIR(entry.lstat().st_mode):raise Refused('unknown_package_entry')
            files=list(entry.iterdir())
            if len(files)>3:raise Refused('unknown_package_entry')
            for path in files:
                info=path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise Refused('unknown_package_entry')
                total+=info.st_size
        return total
    def publish_export(self,request,epoch):
        self.epoch_check(epoch);self.validate_request(request)
        old=self.db.execute('SELECT state FROM publications WHERE request=?',(request,)).fetchone()
        if old:
            if old[0]=='PUBLISHED':self.reconcile_publication(request)
            if self.publication_status(request)['state']!='PUBLISHED':raise Refused('publication_requires_reconciliation')
            return self.publication_status(request)
        if self.db.execute("SELECT 1 FROM publications WHERE state NOT IN ('PUBLISHED','CLEANED')").fetchone():raise Refused('publication_requires_reconciliation')
        row=self.db.execute('SELECT state,snapshot,digest,boot,deadline FROM exports WHERE request=?',(request,)).fetchone()
        if row is None or row[0]!='SNAPSHOT_READY':raise Refused('snapshot_not_ready')
        if row[3]!=self.boot or boottime()>=row[4]:raise Refused('deadline')
        if hashlib.sha256(row[1].encode()).hexdigest()!=row[2]:raise Refused('snapshot_corrupt')
        bodies=package_bodies(row[1])
        size=sum(map(len,bodies.values()))
        if size>PACKAGE_LIMIT:raise Refused('package_size_budget')
        try:
            directory=self.package_directory()
            if self.disk_usage(directory)+size>FILE_BUDGET:raise Refused('package_byte_budget')
            if len(list(directory.iterdir()))>=32:raise Refused('package_entry_budget')
        except OSError:
            # No intent or package files yet: a repaired retry can use the same
            # fixed snapshot/deadline. Keep RPC errors independent of local paths.
            raise Refused('publication_unavailable') from None
        package=uuid.uuid4().hex
        # Persist reservation/ownership before creating any files. No source hold:
        # the immutable SQLite snapshot remains the sole input.
        self.mutation(lambda:self.db.execute('INSERT INTO publications(request,package,state,bytes,digest) VALUES(?,?,?,?,?)',(request,package,'PREPARING',size,row[2])))
        temporary=directory/('.stage-'+package);final=directory/package
        try:
            temporary.mkdir(mode=0o700)
            info=temporary.lstat()
            self.mutation(lambda:self.db.execute('UPDATE publications SET stage_dev=?,stage_ino=? WHERE request=?',(info.st_dev,info.st_ino,request)))
            for name,data in bodies.items():
                fd=os.open(temporary/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
            for name,data in bodies.items():
                if (temporary/name).read_bytes()!=data:raise Refused('package_verification')
            sync_dir(temporary)
            # Same writer serializes cancellation; deadline is never renewed.
            if boottime()>=row[4]:raise Refused('deadline')
            rename_new(temporary,final)
            sync_dir(directory)
            self.mutation(lambda:self.db.execute("UPDATE publications SET state='PUBLISHED',delivered=1 WHERE request=? AND state='PREPARING'",(request,)))
        except (OSError,Refused):
            # Keep owned artifacts and reservation. No broad cleanup or retry that
            # might overwrite an ambiguously published result.
            with self.db:self.db.execute("UPDATE publications SET state='BLOCKED' WHERE request=?",(request,))
            raise Refused('publication_incomplete')
        return self.publication_status(request)

    def _set_publication(self,request,state,**fields):
        names=['state',*fields];values=[state,*fields.values(),request]
        self.mutation(lambda:self.db.execute('UPDATE publications SET '+','.join(name+'=?' for name in names)+' WHERE request=?',values))
    def _directory_info(self,path):
        info=path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise Refused('unknown_directory')
        return info
    def _contents(self,path,bodies,partial=False):
        self._directory_info(path);inventory={}
        names=[]
        for entry in path.iterdir():
            names.append(entry.name)
            if len(names)>3:raise Refused('unknown_files')
        if (not partial and set(names)!=set(bodies)) or not set(names)<=set(bodies):raise Refused('unknown_files')
        for name in names:
            fd=os.open(path/name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            with os.fdopen(fd,'rb') as stream:
                info=os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_nlink!=1 or info.st_size>len(bodies[name]):raise Refused('unknown_file')
                data=stream.read(len(bodies[name])+1)
            if (not partial and data!=bodies[name]) or not bodies[name].startswith(data):raise Refused('unknown_content')
            inventory[name]=dict(dev=info.st_dev,ino=info.st_ino,size=len(data),digest=hashlib.sha256(data).hexdigest())
        return inventory
    def reconcile_publication(self,request,cancel=False):
        self.validate_request(request)
        row=self.db.execute('SELECT package,state,bytes,digest,stage_dev,stage_ino,cleanup,outcome,delivered FROM publications WHERE request=?',(request,)).fetchone()
        if row is None:raise Refused('publication_not_found')
        package,state,size,digest,dev,ino,cleanup,outcome,delivered=row
        if state=='CLEANED':return
        try:
            if not re.fullmatch('[0-9a-f]{32}',package):raise Refused('unknown_package')
            directory=self.package_directory();temporary=directory/('.stage-'+package);final=directory/package
            snapshot=self.db.execute('SELECT snapshot,digest,boot,deadline FROM exports WHERE request=?',(request,)).fetchone()
            if snapshot is None or snapshot[0] is None or snapshot[1]!=digest or hashlib.sha256(snapshot[0].encode()).hexdigest()!=digest:raise Refused('snapshot_mismatch')
            bodies=package_bodies(snapshot[0])
            if sum(map(len,bodies.values()))!=size:raise Refused('reservation_mismatch')
            # lexists detects dangling symlinks too; no unknown object is removed.
            final_exists=os.path.lexists(final);stage_exists=os.path.lexists(temporary)
            if final_exists:
                if stage_exists or cleanup is not None:raise Refused('ambiguous_layout')
                info=self._directory_info(final)
                if ino is not None and (info.st_dev,info.st_ino)!=(dev,ino):raise Refused('directory_replaced')
                self._contents(final,bodies);sync_dir(final);sync_dir(directory)
                self._set_publication(request,'PUBLISHED',delivered=1);return
            if state=='PUBLISHED' or delivered:raise Refused('published_missing')
            if cleanup is not None:
                # Persistent cleanup intent authorizes only the captured files.
                if outcome not in ('CANCELLED','EXPIRED','INTERRUPTED'):raise Refused('cleanup_outcome')
                inventory=json.loads(cleanup)
                if not isinstance(inventory,dict) or not set(inventory)<=set(bodies):raise Refused('cleanup_mismatch')
                if stage_exists:
                    info=self._directory_info(temporary)
                    if ino is None or (info.st_dev,info.st_ino)!=(dev,ino):raise Refused('directory_replaced')
                    actual=self._contents(temporary,bodies,partial=True)
                    if any(name not in inventory or actual[name]!=inventory[name] for name in actual):raise Refused('cleanup_mismatch')
                if cancel:outcome='CANCELLED'
                self._set_publication(request,'CLEANUP_PENDING',outcome=outcome);return
            if stage_exists:
                info=self._directory_info(temporary)
                if ino is None or (info.st_dev,info.st_ino)!=(dev,ino):raise Refused('directory_replaced')
                inventory=self._contents(temporary,bodies,partial=True)
            else:inventory={}
            outcome='CANCELLED' if cancel else ('EXPIRED' if snapshot[2]!=self.boot or boottime()>=snapshot[3] else 'INTERRUPTED')
            self._set_publication(request,'CLEANUP_PENDING',cleanup=json.dumps(inventory,sort_keys=True),outcome=outcome)
        except (OSError,Refused,ValueError,TypeError):self._set_publication(request,'BLOCKED')
    def advance_publications(self):
        if self.degraded:return
        row=self.db.execute("SELECT request FROM publications WHERE state='CLEANUP_PENDING' LIMIT 1").fetchone()
        if row is None:return
        request=row[0];self.reconcile_publication(request)
        row=self.db.execute('SELECT package,state,cleanup,outcome FROM publications WHERE request=?',(request,)).fetchone()
        if row[1]!='CLEANUP_PENDING':return
        try:
            directory=self.package_directory();temporary=directory/('.stage-'+row[0])
            # Reconciliation just checked every remaining inode/content. One file
            # per turn bounds cleanup work; missing files are allowed only after
            # the durable cleanup inventory was committed.
            if os.path.lexists(temporary):
                remaining=list(temporary.iterdir())
                if remaining:
                    remaining[0].unlink();sync_dir(temporary);return
                temporary.rmdir()
            sync_dir(directory)
            def finish():
                self.db.execute("UPDATE publications SET state='CLEANED',bytes=0 WHERE request=? AND state='CLEANUP_PENDING'",(request,))
                self.db.execute('UPDATE exports SET state=?,snapshot=NULL,digest=NULL WHERE request=?',(row[3],request))
            self.mutation(finish)
        except (OSError,Refused):self._set_publication(request,'BLOCKED')
    def reconcile_request(self,request,epoch):
        self.epoch_check(epoch);self.reconcile_publication(request);return self.publication_status(request)
