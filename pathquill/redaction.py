"""Versioned export allowlist. Unknown fields never pass through."""
import ipaddress
import json
import math
import re

class Redactor:
    def __init__(self):self.maps={}
    def alias(self,domain,value):
        value=str(value)
        if domain=='ip':value=str(ipaddress.ip_address(value))
        elif domain=='mac':
            value=re.sub('[:-]','',value).lower()
            if not re.fullmatch('[0-9a-f]{12}|[0-9a-f]{16}',value):raise ValueError('mac')
        else:value=value.rstrip('.').lower().encode('idna').decode('ascii')
        mapping=self.maps.setdefault(domain,{})
        if value not in mapping:mapping[value]=domain+'_'+str(len(mapping)+1)
        return mapping[value]
    def endpoint(self,value):
        try:return self.alias('ip',value)
        except ValueError:
            if re.fullmatch(r'(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}',value):return self.alias('mac',value)
            return self.alias('name',value)
    def interface(self,value):return self.alias('interface',str(int(value)))
    def state(self,group,value):
        a=value.get('attributes',{});result={}
        if group=='links':
            result['interface']=self.interface(value['index'])
            if '3' in a:result['name']=self.alias('name',bytes.fromhex(a['3']).rstrip(b'\0').decode('utf8'))
            if '1' in a:result['mac']=self.alias('mac',a['1'])
        elif group in ('addresses','routes'):
            family=value['family'];result['family']={2:4,10:6}.get(family,'other')
            if group=='addresses':result['interface']=self.interface(value['index'])
            for key,name in ((('1','address'),('2','local')) if group=='addresses' else (('1','destination'),('5','gateway'),('7','preferred_source'))):
                if key in a:result[name]=self.alias('ip',str(ipaddress.ip_address(bytes.fromhex(a[key]))))
            if group=='routes' and '4' in a:result['interface']=self.interface(int.from_bytes(bytes.fromhex(a['4']),'little'))
            prefix=value.get('prefix',value.get('dst_prefix'))
            if type(prefix)==int and 0<=prefix<=128:result['prefix']=prefix
        return result
    def snapshot(self,row,capture):
        state,coverage,reason,recovered,body,first,end=row
        result=dict(schema='pathquill-snapshot-v1',incident=dict(state=state,coverage=coverage,recovered=bool(recovered),end_reason=reason if reason in ('restart','window_end','capacity_gap','resynchronize','receive_error') else 'other',window_seconds=end-first,endpoints=[self.endpoint(v) for v in json.loads(body).get('endpoints',[])]),observations=[])
        for ordinal,(raw,timestamp) in enumerate(capture,1):
            value=json.loads(raw);kind=value.get('kind');event=dict(order=ordinal,kind=kind if kind in ('tcp','dns','progress','state_object','sync','notification','gap') else 'other',relative_seconds=None if timestamp is None else timestamp-first)
            if value.get('outcome') in ('success','refused','timeout','network_error','dns_error','unknown'):event['outcome']=value['outcome']
            if kind=='state_object':event['state']=self.state(value.get('group'),value.get('value',{}))
            if kind=='sync':event['valid']=value.get('valid') is True
            if kind=='notification':event['type']=value.get('type') if value.get('type') in (16,17,20,21,24,25) else 'other'
            result['observations'].append(event)
        return json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False)
