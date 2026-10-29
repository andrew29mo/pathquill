"""Linux-only, no-replace package publication under the existing writer lock."""
import ctypes
import errno
import hashlib
import html
import json
import os
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

class PublicationRecorder(ExportRecorder):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.db.execute('CREATE TABLE IF NOT EXISTS publications(request TEXT PRIMARY KEY,package TEXT UNIQUE,state TEXT,bytes INTEGER,digest TEXT)')
        # P0-4a/b deliberately do not guess which side of rename a crash reached.
        with self.db:self.db.execute("UPDATE publications SET state='BLOCKED' WHERE state='PREPARING'")
    def publication_status(self,request):
        self.validate_request(request)
        row=self.db.execute('SELECT package,state,bytes,digest FROM publications WHERE request=?',(request,)).fetchone()
        if row is None:raise Refused('publication_not_found')
        return dict(package=row[0],state=row[1],bytes=row[2],digest=row[3])
    def cancel_export(self,request,epoch):
        self.epoch_check(epoch);self.validate_request(request)
        row=self.db.execute('SELECT state FROM publications WHERE request=?',(request,)).fetchone()
        if row is not None:raise Refused('already_published' if row[0]=='PUBLISHED' else 'publication_requires_reconciliation')
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
            if old[0]!='PUBLISHED':raise Refused('publication_requires_reconciliation')
            return self.publication_status(request)
        if self.db.execute("SELECT 1 FROM publications WHERE state!='PUBLISHED'").fetchone():raise Refused('publication_requires_reconciliation')
        row=self.db.execute('SELECT state,snapshot,digest,boot,deadline FROM exports WHERE request=?',(request,)).fetchone()
        if row is None or row[0]!='SNAPSHOT_READY':raise Refused('snapshot_not_ready')
        if row[3]!=self.boot or boottime()>=row[4]:raise Refused('deadline')
        if hashlib.sha256(row[1].encode()).hexdigest()!=row[2]:raise Refused('snapshot_corrupt')
        bodies={'snapshot.json':row[1].encode(),'index.html':('<!doctype html><meta charset="utf-8"><pre>'+html.escape(row[1])+'</pre>').encode()}
        manifest=dict(schema='pathquill-package-v1',files={name:dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest()) for name,data in bodies.items()})
        bodies['manifest.json']=json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()
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
        self.mutation(lambda:self.db.execute('INSERT INTO publications VALUES(?,?,?,?,?)',(request,package,'PREPARING',size,row[2])))
        temporary=directory/('.stage-'+package);final=directory/package
        try:
            temporary.mkdir(mode=0o700)
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
            self.mutation(lambda:self.db.execute("UPDATE publications SET state='PUBLISHED' WHERE request=? AND state='PREPARING'",(request,)))
        except (OSError,Refused):
            # Keep owned artifacts and reservation. No broad cleanup or retry that
            # might overwrite an ambiguously published result.
            with self.db:self.db.execute("UPDATE publications SET state='BLOCKED' WHERE request=?",(request,))
            raise Refused('publication_incomplete')
        return self.publication_status(request)
