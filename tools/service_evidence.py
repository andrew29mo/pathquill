"""Fail-closed interpretation of current systemd manager journal evidence."""
import uuid

def rate_limit_proof(records,unit,boot,since_us,burst):
    current=[]
    boot=uuid.UUID(boot).hex
    for record in records:
        try:
            valid=(record.get('_PID')=='1' and record.get('UNIT')==unit and uuid.UUID(record.get('_BOOT_ID','')).hex==boot and int(record.get('__MONOTONIC_TIMESTAMP','-1'))>=since_us)
        except (ValueError,TypeError,AttributeError):valid=False
        if valid:current.append(record)
    limited=any(record.get('MESSAGE')==unit+': Start request repeated too quickly.' for record in current)
    starts=sum(isinstance(record.get('MESSAGE'),str) and record['MESSAGE'].startswith('Started '+unit+' ') for record in current)
    if not limited or starts!=burst:raise ValueError('missing_current_rate_limit_proof')
    return dict(actual_started_events=starts,current_boot_pid1_limit_event=True)

def sealed_exit_proof(records,unit,boot,since_us):
    import json
    boot=uuid.UUID(boot).hex;starts=0;sealed_invocations=set();exits=[]
    for record in records:
        try:
            if uuid.UUID(record.get('_BOOT_ID','')).hex!=boot or int(record.get('__MONOTONIC_TIMESTAMP','-1'))<since_us:continue
        except (ValueError,TypeError,AttributeError):continue
        if record.get('_PID')=='1' and record.get('UNIT')==unit and str(record.get('MESSAGE','')).startswith('Started '+unit+' '):starts+=1
        if record.get('_SYSTEMD_UNIT')!=unit:continue
        try:invocation=uuid.UUID(record.get('_SYSTEMD_INVOCATION_ID','')).hex
        except (ValueError,TypeError,AttributeError):continue
        if record.get('MESSAGE')=='store_sealed':sealed_invocations.add(invocation)
        try:body=json.loads(record.get('MESSAGE',''))
        except (ValueError,TypeError):continue
        if isinstance(body,dict) and body.get('schema')=='pathquill-service-exit-v1' and body.get('invocation')==invocation and body.get('result')=='success' and body.get('code')=='exited' and body.get('status')=='78':exits.append(invocation)
    if starts!=1 or len(exits)!=1 or exits[0] not in sealed_invocations:raise ValueError('missing_current_sealed_exit_proof')
    return dict(permanent_exit_status=78,actual_started_events=starts,matching_invocation_exit_receipt=True)
