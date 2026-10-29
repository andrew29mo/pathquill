"""Fixed acceptance limits for the bounded installed-service observation."""
import statistics

LIMITS=dict(duration_seconds=300,minimum_cycles=6,sample_interval_seconds=2,
            warmup_seconds=45,rss_span_kib=8192,rss_window_growth_kib=2048,
            fd_span=4,thread_span=0,store_allocated_bytes=24*1024*1024)

def resource_check(samples,limits=LIMITS):
    if len(samples)<20:raise ValueError('insufficient_samples')
    if samples[0]['seconds']>6 or samples[0]['seconds']<0:raise ValueError('missing_observation_start')
    if any(b['seconds']<=a['seconds'] for a,b in zip(samples,samples[1:])):raise ValueError('sample_order')
    if samples[-1]['seconds']<limits['duration_seconds']:raise ValueError('short_observation')
    if len({(s['pid'],s['invocation'],s['epoch']) for s in samples})!=1:raise ValueError('service_restarted')
    if any(s['restarts']!=0 for s in samples):raise ValueError('restart_count')
    if any(b['seconds']-a['seconds']>6 for a,b in zip(samples,samples[1:])):raise ValueError('sample_gap')
    warm=[s for s in samples if s['seconds']>=limits['warmup_seconds']]
    if len(warm)<20:raise ValueError('insufficient_warm_samples')
    rss=[s['rss_kib'] for s in warm];fds=[s['fds'] for s in warm];threads=[s['threads'] for s in warm]
    growth=statistics.median(rss[-10:])-statistics.median(rss[:10])
    summary=dict(rss_min_kib=min(rss),rss_max_kib=max(rss),rss_window_growth_kib=growth,
                 fd_min=min(fds),fd_max=max(fds),thread_min=min(threads),thread_max=max(threads),
                 allocated_store_max_bytes=max(s['allocated_store_bytes'] for s in samples))
    if max(rss)-min(rss)>limits['rss_span_kib'] or growth>limits['rss_window_growth_kib']:raise ValueError('rss_growth')
    if max(fds)-min(fds)>limits['fd_span']:raise ValueError('fd_growth')
    if max(threads)-min(threads)>limits['thread_span']:raise ValueError('thread_growth')
    if summary['allocated_store_max_bytes']>limits['store_allocated_bytes']:raise ValueError('store_growth')
    return summary

def cleanup_safe(stop_code,pid,active,members):
    return stop_code==0 and pid=='0' and active in ('inactive','failed') and not members.strip()

def snapshot_evidence(snapshot):
    import math
    from collections import Counter
    if snapshot.get('schema')!='pathquill-snapshot-v1':raise ValueError('snapshot_schema')
    incident=snapshot['incident']
    if incident['state']!='SEALED' or incident['recovered'] is not True or incident['window_seconds']<30:raise ValueError('snapshot_incident')
    rows=snapshot['observations'];orders=[row['order'] for row in rows]
    if orders!=list(range(1,len(rows)+1)):raise ValueError('snapshot_order')
    tcp=[r for r in rows if r['kind']=='tcp']
    if any(type(r['relative_seconds']) not in (float,int) or not math.isfinite(r['relative_seconds']) for r in tcp):raise ValueError('snapshot_time')
    # This workload creates a new incident immediately after a failed TCP probe.
    # Prebuffer may contain older failures; require this incident's trigger too.
    failed=[r for r in tcp if r.get('outcome') in ('refused','timeout','network_error') and -2<=r['relative_seconds']<=2]
    if not failed:raise ValueError('snapshot_trigger_missing')
    recovered=[r for r in tcp if r.get('outcome')=='success' and r['order']>failed[-1]['order'] and r['relative_seconds']>failed[-1]['relative_seconds']]
    if not recovered:raise ValueError('snapshot_recovery_missing')
    return dict(outcomes=dict(Counter(r.get('outcome') for r in tcp)),trigger_relative_seconds=failed[-1]['relative_seconds'],first_recovery_relative_seconds=recovered[0]['relative_seconds'])
