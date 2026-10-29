"""Read-only Linux route notifications; truncation/loss is never suppressed."""
import socket
import struct

class RouteSocket:
    def __init__(self):
        self.socket=socket.socket(socket.AF_NETLINK,socket.SOCK_RAW,0)
        self.socket.bind((0,1|0x10|0x100|0x40|0x400));self.socket.settimeout(2);self.sequence=0
    def receive(self):
        data,anc,flags,peer=self.socket.recvmsg(65536)
        if flags&socket.MSG_TRUNC:raise BufferError('netlink_truncated')
        messages=[];offset=0
        while offset<len(data):
            if offset+16>len(data):raise ValueError('short_header')
            size,kind,flag,seq,pid=struct.unpack_from('IHHII',data,offset)
            if size<16 or offset+size>len(data):raise ValueError('bad_length')
            messages.append(dict(kind=kind,flags=flag,sequence=seq,payload=data[offset+16:offset+size].hex()))
            offset+=(size+3)&~3
        return messages
    def close(self):self.socket.close()
    def synchronize(self):
        import time
        # Subscribe before issuing any dump; unsolicited events remain evidence.
        result=dict(valid=False,dumps=[],notifications=[])
        try:
            for kind in (18,22,26):
                self.sequence=getattr(self,'sequence',0)+1;seq=self.sequence
                start=time.monotonic();payload=bytes(16 if kind==18 else 8 if kind==22 else 12)
                self.socket.send(struct.pack('IHHII',16+len(payload),kind,0x301,seq,0)+payload)
                count=0;deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    messages=self.receive()
                    done=False
                    for m in messages:
                        if m['kind']==4:raise BufferError('netlink_overrun')
                        if m['sequence']!=seq:
                            if m['sequence']!=0:continue  # stale dump reply, not a notification
                            result['notifications'].append(m)
                            if len(result['notifications'])>4096:raise BufferError('notification_budget')
                            continue
                        if m['flags']&0x10:raise BufferError('dump_interrupted')
                        if m['kind']==2:raise OSError('dump_error')
                        if m['kind']==3:
                            payload=bytes.fromhex(m['payload'])
                            if len(payload)>=4 and struct.unpack_from('i',payload)[0]!=0:raise OSError('dump_done_error')
                            done=True
                        else:count+=1
                    if done:break
                else:raise TimeoutError('dump_timeout')
                result['dumps'].append(dict(kind=kind,count=count,start=start,end=time.monotonic()))
            result['valid']=True
        except (OSError,ValueError,BufferError,TimeoutError) as exc:result['error']=type(exc).__name__+': '+str(exc)
        return result
