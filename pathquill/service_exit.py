"""Private systemd stop receipt; no state mutation or arbitrary environment dump."""
import json
import os
import signal
import uuid

def receipt(environment):
    result=environment.get('SERVICE_RESULT')
    if result not in {'success','exit-code','signal','core-dump','timeout','watchdog','start-limit-hit','resources','protocol','oom-kill','exec-condition'}:result='unknown'
    code=environment.get('EXIT_CODE')
    if code not in {'exited','killed','dumped'}:code='unknown'
    status=environment.get('EXIT_STATUS','')
    signals={value.name.removeprefix('SIG') for value in signal.Signals}
    if status.isdecimal() and len(status)<=3 and 0<=int(status)<=255:status=str(int(status))
    elif status not in signals:status='unknown'
    try:invocation=uuid.UUID(environment.get('INVOCATION_ID','')).hex
    except (ValueError,TypeError,AttributeError):invocation=None
    return dict(schema='pathquill-service-exit-v1',result=result,code=code,status=status,invocation=invocation)

def main():print(json.dumps(receipt(os.environ),sort_keys=True))
if __name__=='__main__':main()
