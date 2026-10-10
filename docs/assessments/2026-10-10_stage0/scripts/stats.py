import json, sys
from collections import Counter
ALL=["shipment_overview","journey","custody_chain","scans","delivery_attempts","vehicle_and_manifest","device_status","address_and_instructions","policy","precedents"]
for run in sys.argv[1:]:
    d=json.load(open(run+'/pipeline.json'))
    cs=d['cases']
    print('=====',run, 'commit', d['provenance'].get('commit','')[:7], 'cases',len(cs), 'acc', d['metrics']['root_cause_accuracy'])
    keys=set(cs[0].keys()); 
    ok=lambda c: c['primary_cause'] in (c['acceptable_causes'] or [])
    tc=[c['tool_calls'] for c in cs]
    print(' mean tool calls %.2f median %s min %s max %s; at budget(10): %d' % (sum(tc)/len(tc), sorted(tc)[len(tc)//2], min(tc), max(tc), sum(t>=10 for t in tc)))
    for grp,name in ((lambda c: ok(c),'correct'),(lambda c: not ok(c),'wrong')):
        g=[c for c in cs if grp(c)]
        if not g: continue
        print(' %s n=%d mean calls %.2f' % (name,len(g),sum(c['tool_calls'] for c in g)/len(g)))
        for t in ALL:
            n=sum(t in c['tools'] for c in g)
            print('    %-26s used in %2d/%2d (%.0f%%)' % (t,n,len(g),100*n/len(g)))
    cnt=Counter(t for c in cs for t in c['tools'])
    print(' total calls by tool', dict(cnt))
    rep=sum(len(c['tools'])-len(set(c['tools'])) for c in cs)
    print(' repeated same-tool calls', rep)
    # review outcomes
    tab=Counter()
    for c in cs:
        tab[(c.get('review'), c.get('review_rounds'), 'ok' if ok(c) else 'wrong')]+=1
    for k,v in sorted(tab.items(), key=str): print('  review',k,v)
    rr=[c for c in cs if (c.get('authority_reason') or '').startswith('Reviewer rejected')]
    print(' escalated by Reviewer rejected:', len(rr), 'correct among them', sum(ok(c) for c in rr), [c['shipment_id'][-6:]+':'+str(c['primary_cause']) for c in rr])
    print(' cited mean: ACCEPT %.2f / REVISE-final %.2f' % (
        sum(c['cited'] for c in cs if c['review']=='ACCEPT')/max(1,sum(c['review']=='ACCEPT' for c in cs)),
        sum(c['cited'] for c in cs if c['review']=='REVISE')/max(1,sum(c['review']=='REVISE' for c in cs))))
    # wrong cases skipping device_status / custody_chain
    w=[c for c in cs if not ok(c) and c['primary_cause'] is not None]
    print(' wrong (non-degraded) n=%d: skipped device_status %d, skipped custody_chain %d, skipped vehicle_and_manifest %d, skipped delivery_attempts %d' % (len(w), sum('device_status' not in c['tools'] for c in w), sum('custody_chain' not in c['tools'] for c in w), sum('vehicle_and_manifest' not in c['tools'] for c in w), sum('delivery_attempts' not in c['tools'] for c in w)))
    print(' degraded', sum(bool(c['degraded']) for c in cs), [ (c['shipment_id'][-6:], c['degraded']) for c in cs if c['degraded']])
    # confusion
    conf=Counter((c['truth_recipe'], str(c['primary_cause'])) for c in cs if not ok(c))
    print(' wrong pairs', dict(conf))
