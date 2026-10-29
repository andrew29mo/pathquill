"""Offline in-place archive receipt and explicit fresh-store creation. No rollover."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from .core import Refused
from .publication import PublicationRecorder,package_bodies,sync_dir

def private_file(path):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise Refused('archive_unknown_file')
    return info

def read_file(path,limit):
    info=private_file(path)
    if info.st_size>limit:raise Refused('archive_file_budget')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:return stream.read(limit+1)

@contextlib.contextmanager
def locked_archive(root,expected):
    root=Path(root)
    if not root.is_absolute():raise Refused('absolute_path_required')
    info=root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise Refused('private_owned_directory_required')
    fd=os.open(root/'writer.lock',os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_nlink!=1:raise Refused('archive_unknown_lock')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise Refused('writer_busy') from None
        private_file(root/'state.db')
        db=sqlite3.connect((root/'state.db').as_uri()+'?mode=ro',uri=True)
        try:
            if db.execute("SELECT value FROM meta WHERE key='store_id'").fetchone()!=(expected,):raise Refused('store_mismatch')
            if db.execute("SELECT value FROM meta WHERE key='lifecycle'").fetchone()!=('SEALED',):raise Refused('store_not_sealed')
            if db.execute('PRAGMA quick_check').fetchone()!=('ok',):raise Refused('archive_database_invalid')
            yield root,db
        finally:db.close()
    finally:os.close(fd)

def receipt_bytes(root,db,store):
    allowed={'state.db','writer.lock','packages','archive.json','.archive.pending'}
    for entry in root.iterdir():
        if entry.name not in allowed:raise Refused('archive_unknown_entry')
    files={}
    def record(path,expected=None):
        info=private_file(path)
        if info.st_nlink!=1:raise Refused('archive_unknown_file')
        digest=hashlib.sha256()
        with path.open('rb') as stream:
            while part:=stream.read(65536):digest.update(part)
        if expected is not None and (info.st_size!=len(expected) or digest.hexdigest()!=hashlib.sha256(expected).hexdigest()):raise Refused('archive_content_mismatch')
        files[str(path.relative_to(root))]=dict(bytes=info.st_size,sha256=digest.hexdigest())
    record(root/'state.db')
    rows=db.execute('SELECT request,package,state,stage_dev,stage_ino FROM publications').fetchall()
    if any(row[2] not in ('PUBLISHED','CLEANED') for row in rows):raise Refused('archive_unresolved_publication')
    published={row[1]:row for row in rows if row[2]=='PUBLISHED'}
    directory=root/'packages'
    if os.path.lexists(directory):
        info=directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise Refused('archive_unknown_directory')
        names=[]
        for entry in directory.iterdir():
            names.append(entry.name)
            if len(names)>32:raise Refused('archive_entry_budget')
        if set(names)!=set(published):raise Refused('archive_unknown_entry')
        for package,row in published.items():
            if not re.fullmatch('[0-9a-f]{32}',package):raise Refused('archive_unknown_entry')
            final=directory/package;info=final.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or (row[4] is not None and (info.st_dev,info.st_ino)!=(row[3],row[4])):raise Refused('archive_unknown_directory')
            snapshot=db.execute('SELECT snapshot,digest FROM exports WHERE request=?',(row[0],)).fetchone()
            if snapshot is None or snapshot[0] is None or hashlib.sha256(snapshot[0].encode()).hexdigest()!=snapshot[1]:raise Refused('archive_content_mismatch')
            bodies=package_bodies(snapshot[0])
            if {p.name for p in final.iterdir()}!=set(bodies):raise Refused('archive_unknown_entry')
            for name,data in bodies.items():record(final/name,data)
    elif published:raise Refused('archive_content_mismatch')
    result=dict(schema='pathquill-private-archive-v1',store_id=store,history_used=db.execute('SELECT count(*) FROM exports').fetchone()[0],files=files)
    return json.dumps(result,sort_keys=True,separators=(',',':')).encode()

def sync_file(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

def archive_store(root,store):
    with locked_archive(root,store) as (root,db):
        data=receipt_bytes(root,db,store);receipt=root/'archive.json';pending=root/'.archive.pending'
        if os.path.lexists(receipt):
            if read_file(receipt,65536)!=data:raise Refused('archive_receipt_mismatch')
            if os.path.lexists(pending):
                if pending.lstat().st_ino!=receipt.lstat().st_ino or pending.lstat().st_dev!=receipt.lstat().st_dev:raise Refused('archive_unknown_pending')
                pending.unlink();sync_dir(root)
            sync_file(receipt);sync_dir(root)
            return json.loads(data)
        if os.path.lexists(pending):
            if read_file(pending,65536)!=data or pending.lstat().st_nlink!=1:raise Refused('archive_incomplete')
        else:
            fd=os.open(pending,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        sync_file(pending)
        os.link(pending,receipt,follow_symlinks=False);sync_dir(root);pending.unlink();sync_dir(root)
        return json.loads(data)

def new_store(root,archive,store):
    root=Path(root)
    if not root.is_absolute():raise Refused('absolute_path_required')
    if not Path(archive).is_absolute():raise Refused('absolute_archive_path_required')
    root=root.resolve();archive=Path(archive).resolve()
    if root==archive or archive in root.parents or root in archive.parents:raise Refused('distinct_store_path_required')
    with locked_archive(archive,store) as (old,db):
        if os.path.lexists(old/'.archive.pending'):raise Refused('archive_requires_reconciliation')
        if read_file(old/'archive.json',65536)!=receipt_bytes(old,db,store):raise Refused('archive_receipt_mismatch')
        try:root.mkdir(mode=0o700)
        except FileExistsError:raise Refused('new_store_exists') from None
        r=PublicationRecorder(root)
        try:
            with r.db:r.db.execute("INSERT INTO meta VALUES('parent_store',?)",(store,))
            sync_dir(root);sync_dir(root.parent)
            return dict(store_id=r.store_id,lifecycle='OPEN',parent_store=store)
        finally:r.close()
