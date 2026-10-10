import pickle,collections,sys,json,statistics
from datetime import timedelta
sys.path.insert(0,'.')
SP=r'C:\Users\fbass\AppData\Local\Temp\claude\C--Projects-demo\17973904-12dd-4d61-94d9-456471fdea38\scratchpad'
w,t=pickle.load(open(SP+r'\world.pkl','rb'))
from dataset_v2.contracts import instant
from dataset_v2.derive import custody_corroborated
NORMAL={'on_time','next_day','second_attempt','accounted_return','bulky_normal','fulfillment','contractor_on_time','contractor_second_attempt','late_upload_within_tolerance','duplicate_provider_events'}
A=[n for n in w.of_kind('VehicleAssignment')]
# vehicle sharing
byveh=collections.defaultdict(list)
for a in A: byveh[a.properties['vehicle_id']].append(a)
maxconc=0; conc_hist=collections.Counter()
for v,al in byveh.items():
    for a in al:
        s,e=instant(a.properties['valid_from']),instant(a.properties['valid_to'])
        k=sum(1 for b in al if instant(b.properties['valid_from'])<e and instant(b.properties['valid_to'])>s)
        conc_hist[k]+=1
print('assignments',len(A),'vehicles used',len(byveh),'concurrent assignments per vehicle (incl self):',dict(conc_hist))
modes=collections.Counter(a.properties['mode'] for a in A); print('assignments by mode',dict(modes))
pk=[len(a.properties['package_ids']) for a in A if a.properties['mode']=='last_mile']
print('parcels per last-mile assignment: mean',round(statistics.mean(pk),2),'max',max(pk))
drv=collections.Counter(n.properties['driver_id'] for n in w.of_kind('Vehicle')); print('vehicles',len(w.of_kind('Vehicle')),'drivers',len(w.of_kind('Driver')),'max vehicles per driver',max(drv.values()))
# sessions per shipment
ds=w.of_kind('DeliverySession'); print('DeliverySession nodes',len(ds),'shared across shipments:',sum(1 for d in ds if not d.properties.get('holdout_group')))
lh=[a for a in A if a.properties['mode']=='linehaul']; print('linehaul assignments',len(lh),'distinct linehaul vehicles',len({a.properties['vehicle_id'] for a in lh}),'shipments per linehaul assignment: 1 by construction; mean pkgs',round(statistics.mean(len(a.properties['package_ids']) for a in lh),2))
kinds=set(n.kind for n in w.nodes.values()); print('container/pallet/trip kinds present:',[k for k in kinds if any(x in k.lower() for x in ('container','pallet','trip','cage','bag','tote','route_run'))])
# addresses
coords=collections.defaultdict(set)
for av in w.of_kind('AddressVersion'):
    coords[(av.properties['city'],av.properties['version'])].add((round(av.properties['lat'],6),round(av.properties['lng'],6)))
print('distinct address coordinates per (city,version):',{k:len(v) for k,v in sorted(coords.items())})
print('AddressVersion total',len(w.of_kind('AddressVersion')))
gates=collections.Counter(n.properties['gate'] for n in w.of_kind('DeliveryInstruction')); print('instruction gates',dict(gates))
# healthy timing offsets: corroborated custody vs ExpectedMilestone 'when' (earliest+15m)
off=collections.Counter()
for sid,r in t.items():
    if r['recipe'] not in NORMAL or not r['healthy']: continue
    ems=[n for n in w.owned(sid,'ExpectedMilestone')]
    evs=[n for n in w.owned(sid,'CustodyEvent')]
    for em in ems:
        p=em.properties; when=instant(p['earliest_at'])+timedelta(minutes=15)
        hits=[e for e in evs if e.properties['event_type']==p['predicate'] and p['location_id'] in (e.properties['to_id'],e.properties.get('facility_id')) and e.properties['package_id']==p['package_id']]
        if hits:
            d=(min(instant(e.properties['occurred_at']) for e in hits)-when).total_seconds()/60
            off[round(d) if p['predicate']!='DELIVERED' else 'DELIVERED:'+str(round(d))]+=1
print('healthy observed-minus-planned minutes (non-DELIVERED keys are exact):',dict(off.most_common(8)))
# upload lag for healthy
lag=collections.Counter()
for n in w.of_kind('CustodyEvent'):
    sid=n.properties['holdout_group']
    if sid in t and t[sid]['healthy']:
        lag[round((instant(n.properties['recorded_at'])-instant(n.properties['occurred_at'])).total_seconds()/60)]+=1
print('healthy custody recorded-occurred minutes (pre-feed):',dict(lag))
# outages
outs=[(r['physical']['device_id'],r['physical']['offline_from'],r['physical']['natural_reconnect_at'],sid,r['split']) for sid,r in t.items() if r['recipe']=='offline_device_sync']
aff=collections.Counter()
for sid,r in t.items():
    if r.get('outage_affected_event_ids') and r['recipe']!='offline_device_sync': aff[r['split']]+=1
print('offline_device_sync outages',len(outs),'by split',collections.Counter(o[4] for o in outs),'other shipments affected by split',dict(aff))
dur=[(instant(o[2])-instant(o[1])).total_seconds()/3600 for o in outs]; print('outage durations h',set(dur))
# heartbeats by device kind
hb=collections.Counter()
for n in w.of_kind('DeviceHeartbeat'):
    d=w.nodes[n.properties['device_id']]; hb[(d.properties['device_kind'], d.properties.get('facility_id','').split('-')[1] if d.properties.get('facility_id') else d.properties.get('provider_id'))]+=1
print('heartbeats by (device_kind, facility type/provider):',dict(hb))
devs=collections.Counter((n.properties['device_kind'], n.properties.get('facility_id','-').split('-')[1] if n.properties.get('facility_id') else '') for n in w.of_kind('Device')); print('devices:',dict(devs))
