"""Verify public demo bytes before copying a real product export for publication."""
import hashlib,json
from tools.closeout_checks import snapshot_evidence

def verify_package(files,sensitive):
    if set(files)!={'snapshot.json','index.html','manifest.json'}:raise ValueError('package_members')
    manifest=json.loads(files['manifest.json'])
    if manifest.get('schema')!='pathquill-package-v1' or set(manifest.get('files',{}))!={'snapshot.json','index.html'}:raise ValueError('manifest_contract')
    for name,item in manifest['files'].items():
        if item!={'bytes':len(files[name]),'sha256':hashlib.sha256(files[name]).hexdigest()}:raise ValueError('manifest_mismatch')
    for value in sensitive:
        if value and any(value.lower().encode() in body.lower() for body in files.values()):raise ValueError('sensitive_value')
    snapshot=json.loads(files['snapshot.json']);proof=snapshot_evidence(snapshot)
    groups={row['group'] for row in snapshot['observations'] if row['kind']=='state_object'}
    if groups!={'links','addresses','routes'}:raise ValueError('state_context_missing')
    endpoint=snapshot['incident']['endpoints'][0]
    if not any(row.get('state',{}).get('local',row.get('state',{}).get('address'))==endpoint for row in snapshot['observations'] if row.get('group')=='addresses'):raise ValueError('endpoint_alias_relation')
    import html
    if html.unescape(files['index.html'].decode().split('<pre>',1)[1].split('</pre>',1)[0]).encode()!=files['snapshot.json']:raise ValueError('html_snapshot_mismatch')
    return dict(tcp=proof,observations=len(snapshot['observations']),state_groups=sorted(groups),sensitive_values_checked=len(sensitive),files={name:dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest()) for name,data in files.items()})
