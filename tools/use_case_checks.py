"""Verify public demo bytes before copying a real product export for publication."""
import hashlib,json,html,os,uuid
from tools.closeout_checks import snapshot_evidence

def verify_package(files,sensitive):
    if set(files)!={'snapshot.json','index.html','manifest.json'}:raise ValueError('package_members')
    manifest=json.loads(files['manifest.json'])
    if manifest.get('schema')!='pathquill-package-v1' or set(manifest.get('files',{}))!={'snapshot.json','index.html'}:raise ValueError('manifest_contract')
    for name,item in manifest['files'].items():
        if item!={'bytes':len(files[name]),'sha256':hashlib.sha256(files[name]).hexdigest()}:raise ValueError('manifest_mismatch')
    snapshot=json.loads(files['snapshot.json'])
    decoded=[json.dumps(x,ensure_ascii=False).encode() for x in (snapshot,manifest)]
    for value in sensitive:
        if value and any(value.lower().encode() in body.lower() for body in [*files.values(),*decoded]):raise ValueError('sensitive_value')
    proof=snapshot_evidence(snapshot)
    groups={row['group'] for row in snapshot['observations'] if row['kind']=='state_object'}
    if groups!={'links','addresses','routes'}:raise ValueError('state_context_missing')
    endpoint=snapshot['incident']['endpoints'][0]
    rows=snapshot['observations']
    addresses=[r['state'] for r in rows if r.get('group')=='addresses' and r.get('state',{}).get('local',r.get('state',{}).get('address'))==endpoint]
    interfaces={a.get('interface') for a in addresses if a.get('family')==4 and a.get('prefix')==24};interfaces.discard(None)
    if not interfaces:raise ValueError('endpoint_alias_relation')
    links=[r['state'] for r in rows if r.get('group')=='links' and r.get('state',{}).get('interface') in interfaces]
    if not any(str(x.get('name','')).startswith('name_') and str(x.get('mac','')).startswith('mac_') for x in links):raise ValueError('link_context_missing')
    routes=[r['state'] for r in rows if r.get('group')=='routes' and r.get('state',{}).get('interface') in interfaces]
    if not any(x.get('family')==4 and str(x.get('destination','')).startswith('ip_') and type(x.get('prefix'))==int for x in routes):raise ValueError('route_context_missing')
    expected=('<!doctype html><meta charset="utf-8"><pre>'+html.escape(files['snapshot.json'].decode())+'</pre>').encode()
    if files['index.html']!=expected:raise ValueError('html_snapshot_mismatch')
    return dict(tcp=proof,observations=len(snapshot['observations']),state_groups=sorted(groups),sensitive_values_checked=len(sensitive),files={name:dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest()) for name,data in files.items()})


def private_outputs(root):
    """Private records belong to the checkout owner, never a presumed login UID."""
    owner=root.stat();work=root/'results/use-case/runs'/uuid.uuid4().hex
    work.mkdir(mode=0o700,parents=True);os.chown(work,owner.st_uid,owner.st_gid)
    trace=work/'private-cli.jsonl';trace.touch(mode=0o600);os.chown(trace,owner.st_uid,owner.st_gid)
    return work,trace,(owner.st_uid,owner.st_gid)


def retain_attempt(previous):
    return previous.get('passed') is False and previous.get('status')!='in_progress'
