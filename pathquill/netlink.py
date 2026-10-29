"""Read-only Linux route notifications; truncation/loss is never suppressed."""
import socket
import struct

class RouteSocket:
    def __init__(self):
        self.socket=socket.socket(socket.AF_NETLINK,socket.SOCK_RAW,0)
        self.socket.bind((0,1|0x10|0x100|0x40|0x400));self.socket.settimeout(2)
    def receive(self):
        data,anc,flags,peer=self.socket.recvmsg(65536)
        if flags&socket.MSG_TRUNC:raise BufferError('netlink_truncated')
        messages=[];offset=0
        while offset<len(data):
            if offset+16>len(data):raise ValueError('short_header')
            size,kind,flag,seq,pid=struct.unpack_from('IHHII',data,offset)
            if size<16 or offset+size>len(data):raise ValueError('bad_length')
            messages.append(dict(kind=kind,flags=flag,sequence=seq))
            offset+=(size+3)&~3
        return messages
    def close(self):self.socket.close()
