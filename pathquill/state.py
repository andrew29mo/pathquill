"""Bounded read-only state reconstruction. Only quiet reconciled rounds publish."""
import json
import struct

def attrs(payload,start):
    out={};offset=start
    while offset<len(payload):
        if offset+4>len(payload):raise ValueError('short_attribute')
        size,kind=struct.unpack_from('HH',payload,offset)
        if size<4 or offset+size>len(payload):raise ValueError('bad_attribute')
        out[str(kind&0x3fff)]=payload[offset+4:offset+size].hex();offset+=(size+3)&~3
    return out

def decode(message):
    kind=message['kind'];p=bytes.fromhex(message['payload'])
    if kind in (16,17):
        if len(p)<16:raise ValueError('short_link')
        family,pad,typ,index,flags,change=struct.unpack_from('BBHiII',p)
        a=attrs(p,16)
        return 'links',str(index),dict(index=index,type=typ,flags=flags,attributes={k:v for k,v in a.items() if k in ('1','3','4','16','18')})
    if kind in (20,21):
        if len(p)<8:raise ValueError('short_address')
        family,prefix,flags,scope,index=struct.unpack_from('BBBBI',p);a=attrs(p,8);a.pop('6',None)
        value=dict(family=family,prefix=prefix,flags=flags,scope=scope,index=index,attributes=a)
        return 'addresses',json.dumps(value,sort_keys=True),value
    if kind in (24,25):
        if len(p)<12:raise ValueError('short_route')
        family,dst,src,tos,table,protocol,scope,typ,flags=struct.unpack_from('BBBBBBBBI',p)
        a=attrs(p,12);a.pop('12',None)
        value=dict(family=family,dst_prefix=dst,src_prefix=src,tos=tos,table=table,protocol=protocol,scope=scope,type=typ,flags=flags,attributes=a)
        return 'routes',json.dumps(value,sort_keys=True),value
    raise ValueError('unsupported_notification')

def materialize(records):
    view=dict(links={},addresses={},routes={})
    for m in records:
        group,key,value=decode(m);view[group][key]=value
    return view

class State:
    def __init__(self):self.generation=0;self.status='SYNCING';self.view=None;self.gaps=[]
    def invalidate(self,reason):
        self.generation+=1;self.status='DEGRADED';self.gaps=(self.gaps+[reason])[-32:];self.view=None
    def rebuild(self,backend):
        self.invalidate('resynchronize');previous=None
        for _ in range(3):
            result=backend.synchronize()
            if not result['valid'] or result['notifications']:previous=None;continue
            try:view=materialize(result['records'])
            except (ValueError,KeyError,struct.error):previous=None;continue
            if previous==view:
                self.view=view;self.status='RECORDING';return True
            previous=view
        return False
