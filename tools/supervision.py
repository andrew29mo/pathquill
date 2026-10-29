"""Own a whole worker process group, including descendants on every exit."""
import os
import signal
import subprocess
import time

def run_group(command,timeout):
    process=subprocess.Popen(command,start_new_session=True)
    try:return process.wait(timeout=timeout)
    finally:
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:process.wait(timeout=2)
        except subprocess.TimeoutExpired:pass
        # A worker can exit while descendants still own its session resources.
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait(timeout=3)

def unmount(path):
    # SIGKILL delivery is asynchronous: retry only transient EBUSY, never force.
    environment=dict(os.environ,LC_ALL='C')
    for attempt in range(10):
        result=subprocess.run(['umount',str(path)],capture_output=True,text=True,timeout=.2,env=environment)
        if result.returncode==0:return
        if 'busy' not in result.stderr.lower() or attempt==9:
            raise subprocess.CalledProcessError(result.returncode,result.args,stderr=result.stderr)
        time.sleep(.05)
