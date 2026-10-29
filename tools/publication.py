"""Actual daemon/CLI package publication in an isolated Linux namespace."""
import datetime,hashlib,html,json,os,platform,subprocess,sys,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pathquill.publication import PublicationRecorder
from pathquill.cli import call
from tools.supervision import run_group
FINAL=ROOT/'evidence/publication.json'
def write(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n');path.with_suffix('.html').write_text('<!doctype html><meta charset="utf-8"><pre>'+html.escape(json.dumps(value,indent=2))+'</pre>')
def check(value,message):
    if not value:raise RuntimeError(message)
mode=sys.argv[1] if len(sys.argv)>1 else None
if mode=='orchestrate':
    write(FINAL,dict(passed=False,status='in_progress'))
    try:
        with tempfile.TemporaryDirectory(prefix='pq-publish-report-') as tmp:
            os.chown(tmp,501,501);out=Path(tmp)/'result.json'
            code=run_group([sys.executable,__file__,'worker',str(out)],45)
            result=json.loads(out.read_text())
            required={'preintent_directory_denial_is_structured_and_retryable','formal_cli_complete_sanitized_package_and_dedup','cancel_before_publication_refuses_delivery','real_directory_write_denial_no_false_success'}
            check(code==0 and result['passed'] and {case['name'] for case in result['cases']}==required,'incomplete verification')
        result['orchestrator_cleanup']=True
    except Exception as error:result=dict(passed=False,error=type(error).__name__)
    write(FINAL,result)
    if os.getuid()==0:
        os.chown(FINAL,501,501);os.chown(FINAL.with_suffix('.html'),501,501)
    sys.exit(0 if result['passed'] else 1)
if mode!='worker' or len(sys.argv)!=3:raise SystemExit('Usage: publication.py orchestrate inside isolated Linux VM')
result=dict(passed=False,mvp_qualified=False,cases=[],environment=dict(system=platform.system(),release=platform.release(),python=platform.python_version(),utc=datetime.datetime.now(datetime.timezone.utc).isoformat()),limits=['Synthetic sensitive source fixture, not production incident data','Single writer/private directory; malicious same-UID mutation is outside the trust boundary','Logical file-byte/count limits, not filesystem quota or allocated block accounting','Write failure uses actual directory permission denial; fsync ENOSPC is unit-injected','This runner does not exercise crash recovery; see publication-recovery evidence. No VM reboot or power-loss qualification','No external reader lease, artifact deletion or automatic retention rollover'])
proc=None
try:
    if os.getuid()==0:
        subprocess.run(['ip','link','set','lo','up'],check=True);os.setgroups([]);os.setgid(501);os.setuid(501)
    tests=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover(str(ROOT/'tests'),top_level_dir=str(ROOT)))
    check(tests.wasSuccessful(),'tests failed');result['tests']=tests.testsRun
    with tempfile.TemporaryDirectory(prefix='pq-publish-') as tmp:
        tmp=Path(tmp);root=tmp/'store';seed=PublicationRecorder(root)
        seed.observe(dict(kind='state_object',group='links',value=dict(index=7,attributes={'3':b'PRIVATE-NIC\0'.hex()})),0)
        source=seed.incident(dict(endpoints=['10.23.45.67','PRIVATE.example']),1);seed.finish(source,31,seed.epoch,31);seed.close()
        config=tmp/'config.json';config.write_text('[]');log=tmp/'daemon.log'
        with log.open('wb') as stream:proc=subprocess.Popen([sys.executable,'-m','pathquill.daemon','--root',str(root),'--config',str(config)],cwd=ROOT,stdout=stream,stderr=stream)
        deadline=time.monotonic()+5
        while True:
            try:
                state=call(root)
                if state['state']=='RECORDING':break
            except (OSError,ValueError):pass
            check(time.monotonic()<deadline and proc.poll() is None,'startup failed');time.sleep(.02)
        epoch=state['epoch']
        def cli(op,request,ok=True):
            p=subprocess.run([sys.executable,'-m','pathquill.cli','--root',str(root),'--op',op,'--request',request,'--id',source,'--epoch',epoch,'--seconds','60'],cwd=ROOT,capture_output=True,text=True,timeout=12)
            v=json.loads(p.stdout);check((p.returncode==0)==ok and v['ok']==ok,'CLI exit/reply mismatch');return v
        def ready(request):
            cli('export',request);end=time.monotonic()+6
            while cli('export-status',request)['export']['state']!='SNAPSHOT_READY':
                check(time.monotonic()<end,'snapshot timeout');time.sleep(.05)
        ready('PRIVATE-request');fixed=cli('export-read','PRIVATE-request')['export']
        original_deadline=cli('export-status','PRIVATE-request')['export']['deadline']
        packages=root/'packages';packages.mkdir(mode=0o700);packages.chmod(0o000)
        try:check(cli('export-publish','PRIVATE-request',False)['error']=='publication_unavailable','preintent failure lost structured reply')
        finally:packages.chmod(0o700)
        check(cli('publication-status','PRIVATE-request',False)['error']=='publication_not_found','preintent failure created ownership')
        result['cases'].append(dict(name='preintent_directory_denial_is_structured_and_retryable',passed=True))
        start=time.monotonic();published=cli('export-publish','PRIVATE-request')['export'];elapsed=time.monotonic()-start
        check(published['state']=='PUBLISHED','not published');directory=root/'packages'/published['package']
        check(cli('export-status','PRIVATE-request')['export']['deadline']==original_deadline,'repair extended deadline')
        files={p.name:p.read_bytes() for p in directory.iterdir()};check(set(files)=={'snapshot.json','index.html','manifest.json'},'partial package')
        check(json.loads(files['snapshot.json'])==fixed['snapshot'],'publication changed snapshot content')
        check(files['index.html'].decode()==fixed['preview_html'],'publication changed HTML preview')
        check(hashlib.sha256(files['snapshot.json']).hexdigest()==fixed['digest'],'publication changed fixed JSON bytes')
        check(len(fixed['snapshot']['incident']['endpoints'])==2 and any(event.get('group')=='links' and event.get('state',{}).get('interface') for event in fixed['snapshot']['observations']),'sanitized fixture lost useful content')
        manifest=json.loads(files['manifest.json'])
        check(manifest.get('schema')=='pathquill-package-v1' and set(manifest.get('files',{}))=={'snapshot.json','index.html'},'incomplete manifest')
        for name,entry in manifest['files'].items():check(hashlib.sha256(files[name]).hexdigest()==entry['sha256'] and len(files[name])==entry['bytes'],'manifest mismatch')
        for name,data in files.items():
            for raw in ['10.23.45.67','PRIVATE','PRIVATE-request',source,str(root),'0a172d43']:check(raw not in name+data.decode(),'original value leaked')
        check(cli('export-publish','PRIVATE-request')['export']==published,'retry changed package')
        check(cli('export-cancel','PRIVATE-request',False)['error']=='already_published','cancel rewrote published package')
        check({p.name:p.read_bytes() for p in directory.iterdir()}==files,'package overwritten')
        result['cases'].append(dict(name='formal_cli_complete_sanitized_package_and_dedup',bytes=published['bytes'],cli_publish_seconds=elapsed,passed=True))
        ready('cancel');cli('export-cancel','cancel');check(cli('export-publish','cancel',False)['error']=='snapshot_not_ready','cancel resurrected')
        result['cases'].append(dict(name='cancel_before_publication_refuses_delivery',passed=True))
        ready('denied');packages=root/'packages';packages.chmod(0o500)
        try:check(cli('export-publish','denied',False)['error']=='publication_incomplete','write failure reported success')
        finally:packages.chmod(0o700)
        check(cli('publication-status','denied')['export']['state']=='BLOCKED','failed publication not blocked')
        check(cli('export-publish','denied',False)['error']=='publication_requires_reconciliation','unsafe retry')
        check({p.name:p.read_bytes() for p in directory.iterdir()}==files,'failure damaged earlier package')
        result['cases'].append(dict(name='real_directory_write_denial_no_false_success',passed=True))
        proc.terminate();check(proc.wait(6)==0,'shutdown failed');check(not (root/'control.sock').exists(),'socket leaked')
    result['passed']=True
except Exception as error:result['error']=type(error).__name__+': '+str(error).replace(str(ROOT),'<checkout>')
finally:
    if proc and proc.poll() is None:proc.kill();proc.wait(5)
    result['source']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*sorted((ROOT/'pathquill').glob('*.py')),*sorted((ROOT/'tests').glob('*.py')),ROOT/'tools/publication.py',ROOT/'tools/supervision.py',ROOT/'pyproject.toml']}
    write(Path(sys.argv[2]),result)
sys.exit(0 if result['passed'] else 1)
