import pickle,collections,sys,json
from datetime import timedelta
sys.path.insert(0,'.')
SP=r'C:\Users\fbass\AppData\Local\Temp\claude\C--Projects-demo\17973904-12dd-4d61-94d9-456471fdea38\scratchpad'
w,t=pickle.load(open(SP+r'\world.pkl','rb'))
from dataset_v2.derive import assess_shipment, EvidenceIndex, custody_corroborated, _observed
from dataset_v2.contracts import instant, iso
from operations.store import monitor_finding, DETECTION_ALLOWANCE_SECONDS as DA
from dataset_v2.feed import split_feed, reconstitute
# dev: reconstitute with feed deliver_at as recorded_at (what the live system sees)
imported, items = split_feed(w, t)
full = reconstitute(imported, items)
idx_full = EvidenceIndex(full)
idx_w = EvidenceIndex(w)
FAC=("Branch","Hub","SortingCenter","DeliveryDepot","FulfillmentWarehouse","OrganizationWarehouse")
def hb_state(world, device, cutoff):
    beats=[instant(n.properties['occurred_at']) for n in idx.kinds['DeviceHeartbeat'] if n.properties['device_id']==device and instant(n.properties['recorded_at'])<=cutoff and instant(n.properties['occurred_at'])>=cutoff-timedelta(hours=24)]
    if not beats: return 'NO_TELEMETRY'
    since=(cutoff-max(beats)).total_seconds()/60
    return f'silent{int(since)}m' if since>=90 else 'reporting'
def opening(world, idx, sid):
    owned=idx.groups[sid]
    times=set()
    for kind,nodes in owned.items():
        for n in nodes:
            p=n.properties
            if kind=='ExpectedMilestone':
                times.add(instant(p['latest_at'])+timedelta(seconds=(p.get('grace_seconds') or 0)+DA+1))
            elif kind=='DeliverySession':
                times.add(instant(p['end_at'])+timedelta(seconds=(p.get('grace_seconds') or 0)+DA+61))
            elif p.get('recorded_at') and p.get('occurred_at') and kind not in ('Case','Exception'):
                times.add(instant(p['recorded_at'])+timedelta(seconds=1))
    end=instant(world.nodes[sid].properties.get('as_of') or t[sid].get('as_of','2099-01-01T00:00:00+00:00')) if world.nodes[sid].properties.get('as_of') else None
    for at in sorted(times):
        a=assess_shipment(world,sid,iso(at),_index=idx,detection_allowance_seconds=DA)
        f=monitor_finding(a)
        if f['open']:
            return at,f['symptoms'],a
    return None,[],None
def vector(world, idx, sid, at, a):
    owned=idx.groups[sid]
    vis=lambda n:_observed(n,at)
    v={}
    custody=[n for n in owned['CustodyEvent'] if vis(n)]
    last={}
    for c in sorted(custody,key=lambda n:n.properties['occurred_at']):
        p=c.properties
        if custody_corroborated(world,c,at):
            last[p['package_id']]=(p['event_type'], world.nodes[p['to_id']].kind if p['to_id'] in world.nodes else '?')
    v['last_corr']=sorted(set(last.values()))
    v['uncorr']=sorted({(c.properties['event_type'],world.nodes[c.properties['source_event_id']].properties.get('observation_type') if c.properties['source_event_id'] in world.nodes else None,c.properties['source_quality']) for c in custody if not custody_corroborated(world,c,at)})
    v['missing']=sorted({(x['predicate'],world.nodes[x['location_id']].kind if x['location_id'] in world.nodes else 'Addr') for x in a['expected_vs_actual'] if x.get('missing_due')})
    v['late']=sorted({(x['predicate'],world.nodes[x['location_id']].kind) for x in a['expected_vs_actual'] if x.get('late')})
    st=sorted((n for n in owned['StatusEvent'] if vis(n)),key=lambda n:n.properties['occurred_at'])
    v['status']=st[-1].properties['status'] if st else 'CREATED'
    v['attempts']=sorted({(n.properties['disposition'],n.properties.get('failed_reason')) for n in owned['DeliveryAttempt'] if vis(n)})
    v['contacts']=sorted({n.properties['result'] for n in owned['ContactAttempt'] if vis(n)})
    v['recon']=sorted({n.properties['result'] for n in owned['DepotReconciliation'] if vis(n)})
    v['reports']=len([n for n in owned['RecipientReport'] if vis(n)])
    v['manifest_versions']=sorted({n.properties['version'] for n in owned['Manifest'] if vis(n)})
    v['traffic']=len([n for n in owned['TrafficObservation'] if vis(n)])
    v['gps']=sorted({n.id.rsplit('GPS-',1)[-1] for n in owned['GPSObservation'] if vis(n)})
    lags=[(instant(n.properties['recorded_at'])-instant(n.properties['occurred_at'])).total_seconds()/60 for k in ('CustodyEvent','ScanEvent') for n in owned[k] if vis(n)]
    v['max_lag_min']=round(max(lags,default=0))
    lm=[n for n in owned['VehicleAssignment'] if n.properties.get('mode')=='last_mile']
    drv=world.nodes[lm[0].properties['driver_id']].properties if lm else {}
    v['lm_employment']=drv.get('employment')
    depot=next((n.properties['depot_id'] for n in owned['DeliverySession']),None)
    v['depot_hh']=hb_state(world,'DEMO-DEV-HH-'+depot.removeprefix('DEMO-'),at) if depot else None
    if drv.get('employment')=='INDEPENDENT':
        v['driver_app']=hb_state(world,'DEMO-DEV-APP-'+lm[0].properties['driver_id'].removeprefix('DEMO-'),at)
    v['intercity']=any(n.properties.get('mode')=='linehaul' for n in owned['RouteSegment'])
    v['addr_versions']=len(owned['AddressVersion'])
    v['proof_reasons']=sorted({r for d in a['delivery_assessment'] for p in d['proofs'] for r in p['reasons']})
    return v
out={}
for sid,row in sorted(t.items()):
    if row['healthy']: continue
    if row['split']=='development':
        world,idx=full,idx_full
    else:
        world,idx=w,idx_w
    at,sym,a=opening(world,idx,sid)
    if at is None:
        out[sid]={'recipe':row['recipe'],'split':row['split'],'open':None}; continue
    vec=vector(world,idx,sid,at,a)
    out[sid]={'recipe':row['recipe'],'split':row['split'],'root':row['root_cause'],'acc':row['acceptable_causes'],'secondary':row.get('secondary_issue') or row.get('secondary_effect_of'),'open':iso(at),'symptoms':sym,'codes':a['supported_codes'],'vec':vec}
json.dump(out,open(SP+r'\open.json','w'),indent=1,default=str)
print(len(out))
