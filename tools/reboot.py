"""Two-phase normal VM reboot evidence; inspect raw DB before recovery."""
import hashlib,html,json,os,sqlite3,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pathquill.recorder import Recorder
from pathquill.core import Refused
mode=sys.argv[1];pointer=ROOT/'results/reboot-pointer.json'
def save(v):
    out=ROOT/'evidence/reboot.json';out.write_text(json.dumps(v,indent=2)+'\n');out.with_suffix('.html').write_text('<!doctype html><meta charset="utf-8"><pre>'+html.escape(json.dumps(v,indent=2))+'</pre>')
if mode=='prepare':
    tmp=tempfile.mkdtemp(prefix='pathquill-reboot-',dir='/var/tmp');s=Recorder(tmp)
    s.observe(dict(kind='before_reboot',outcome='success'));key=s.incident(dict(endpoints=['sensitive.example']))
    before=dict(boot=s.boot,epoch=s.epoch,key=key,capture_count=s.db.execute('SELECT count(*) FROM capture').fetchone()[0]);s.close()
    pointer.write_text(json.dumps(dict(root=tmp,before=before)))
    save(dict(passed=False,status='awaiting_real_VM_reboot',before=before))
else:
    v=json.loads(pointer.read_text());before=v['before'];root=Path(v['root']);out=dict(passed=False,before=before,normal_shutdown=True,power_loss_tested=False)
    try:
        boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if boot==before['boot']:raise RuntimeError('same boot')
        db=sqlite3.connect('file:'+str(root/'state.db')+'?mode=ro',uri=True)
        row=db.execute('SELECT state FROM incidents WHERE id=?',(before['key'],)).fetchone();db.close()
        out['raw_before_recovery']=row[0]
        if row[0]!='CAPTURING':raise RuntimeError('pending state not preserved')
        s=Recorder(root)
        row=s.db.execute('SELECT state,coverage,reason FROM incidents').fetchone()
        if row!=('SEALED','PARTIAL','restart'):raise RuntimeError('wrong recovery')
        if s.db.execute('SELECT count(*) FROM capture').fetchone()[0]!=before['capture_count']:raise RuntimeError('lost capture')
        try:s.finish(before['key'],10000,before['epoch'],10000)
        except Refused:pass
        else:raise RuntimeError('stale accepted')
        exported=s.export(before['key'])
        if 'sensitive' in exported['json']:raise RuntimeError('export leaked')
        s.observe(dict(kind='new_boot'));out.update(passed=True,after_boot=boot,recovery=list(row),capture_preserved=True,stale_rejected=True,export_redacted=True,source={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*sorted((ROOT/'pathquill').glob('*.py')),ROOT/'tools/reboot.py']});s.close()
        import shutil;shutil.rmtree(root);pointer.unlink();out['cleanup']=True
    except Exception as e:out['error']=type(e).__name__+': '+str(e)
    save(out);sys.exit(0 if out['passed'] else 1)
