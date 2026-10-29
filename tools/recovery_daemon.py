"""Test-only pause points around actual formal daemon filesystem operations.

No alternate recorder/backend. Parent SIGKILLs the stopped real daemon process.
Not a production entry point; the production daemon has no fault flags.
"""
import os,runpy,signal,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pathquill import publication
fault=sys.argv[1];sys.argv=[str(ROOT/'pathquill/daemon.py'),*sys.argv[2:]]
def pause():os.kill(os.getpid(),signal.SIGSTOP)
rename=publication.rename_new;sync=publication.sync_dir;unlink=Path.unlink
if fault in ('before_rename','after_rename'):
    def boundary(source,destination):
        if fault=='before_rename':pause()
        rename(source,destination)
        if fault=='after_rename':pause()
    publication.rename_new=boundary
elif fault in ('cleanup_unlink','retire_unlink'):
    def boundary(path,*args,**kwargs):
        result=unlink(path,*args,**kwargs)
        if (fault=='cleanup_unlink' and path.parent.name.startswith('.stage-')) or (fault=='retire_unlink' and path.parent.parent.name=='packages' and not path.parent.name.startswith('.stage-')):pause()
        return result
    Path.unlink=boundary
elif fault=='seal_commit':
    seal=publication.PublicationRecorder.seal_store
    def boundary(self,*args,**kwargs):
        result=seal(self,*args,**kwargs);pause();return result
    publication.PublicationRecorder.seal_store=boundary
else:raise SystemExit('unknown test boundary')
runpy.run_module('pathquill.daemon',run_name='__main__')
