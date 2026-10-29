"""Private local status/control client."""
import argparse,json,socket
from pathlib import Path

def call(root,op='status',**fields):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
        s.settimeout(12);s.connect(str(Path(root)/'control.sock'));s.sendall(json.dumps(dict(op=op,**fields)).encode());data=b''
        while True:
            part=s.recv(65536)
            if not part:break
            data+=part
            if len(data)>4194304:raise ValueError('response_budget')
    return json.loads(data)
def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--resync',action='store_true');p.add_argument('--op',choices=['status','gc','delete','hold','release','export','export-status','export-cancel','export-read','export-publish','publication-status','publication-reconcile','publication-retire','store-seal','store-archive','store-new'],default='status');p.add_argument('--store');p.add_argument('--package');p.add_argument('--archive');p.add_argument('--request');p.add_argument('--seconds',type=float,default=30);p.add_argument('--id');p.add_argument('--token');p.add_argument('--epoch');a=p.parse_args()
    if a.op in ('store-archive','store-new'):
        from .archive import archive_store,new_store
        from .core import Refused
        import sqlite3
        try:
            if not a.store:raise Refused('store_required')
            if a.op=='store-new' and not a.archive:raise Refused('archive_required')
            result=archive_store(a.root,a.store) if a.op=='store-archive' else new_store(a.root,a.archive,a.store)
            reply=dict(ok=True,archive=result)
        except Refused as error:reply=dict(ok=False,error=str(error))
        except (OSError,ValueError,sqlite3.Error):reply=dict(ok=False,error='offline_operation_failed')
        print(json.dumps(reply));raise SystemExit(0 if reply['ok'] else 1)
    reply=call(a.root,'resync' if a.resync else a.op,id=a.id,token=a.token,epoch=a.epoch,request=a.request,seconds=a.seconds,store=a.store,package=a.package)
    print(json.dumps(reply));raise SystemExit(0 if reply.get('ok') else 1)
if __name__=='__main__':main()
