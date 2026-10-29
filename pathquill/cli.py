"""Private local status/control client."""
import argparse,json,socket
from pathlib import Path

def call(root,op='status'):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
        s.settimeout(12);s.connect(str(Path(root)/'control.sock'));s.sendall(json.dumps(dict(op=op)).encode());data=b''
        while True:
            part=s.recv(65536)
            if not part:break
            data+=part
            if len(data)>4194304:raise ValueError('response_budget')
    return json.loads(data)
def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--resync',action='store_true');a=p.parse_args();print(json.dumps(call(a.root,'resync' if a.resync else 'status')))
if __name__=='__main__':main()
