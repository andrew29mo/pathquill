"""Pure bounded network operations: workers never touch recorder state."""
import ipaddress,socket,struct

def dns_query(server,port=53,timeout=.3):
    if ipaddress.ip_address(server).version!=4:raise ValueError('DNS IPv4 endpoint required')
    ident=__import__('secrets').randbelow(65536);name=b'\x07example\x04test\x00'
    query=struct.pack('!HHHHHH',ident,0x100,1,0,0,0)+name+struct.pack('!HH',1,1)
    outcome='success'
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout);sock.connect((server,port));sock.send(query);data=sock.recv(4096)
        if len(data)<12:raise ValueError('short_dns')
        rid,flags,qd,an,ns,ar=struct.unpack('!HHHHHH',data[:12])
        if rid!=ident or not flags&0x8000 or flags&0x200 or qd!=1 or data[12:12+len(query)-12]!=query[12:]:raise ValueError('invalid_dns')
        if flags&0x7800:raise ValueError('DNS opcode')
        offset=len(query)
        for _ in range(an+ns+ar):
            while True:
                if offset>=len(data):raise ValueError('truncated_RR_name')
                n=data[offset];offset+=1
                if n==0:break
                if n&0xc0==0xc0:
                    if offset>=len(data) or ((n&63)*256+data[offset])>=len(data):raise ValueError('bad_pointer')
                    offset+=1;break
                if n>63 or offset+n>len(data):raise ValueError('bad_label')
                offset+=n
            if offset+10>len(data):raise ValueError('truncated_RR')
            length=struct.unpack_from('!H',data,offset+8)[0];offset+=10+length
            if offset>len(data):raise ValueError('truncated_RDATA')
        if offset!=len(data):raise ValueError('trailing_DNS_bytes')
        outcome='success' if flags&15==0 else 'dns_error'
    except (OSError,ValueError):outcome='unknown'
    return outcome
