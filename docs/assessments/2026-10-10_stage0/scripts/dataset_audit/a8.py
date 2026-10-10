import pickle,collections,sys
from datetime import timedelta
sys.path.insert(0,'.')
SP=r'C:\Users\fbass\AppData\Local\Temp\claude\C--Projects-demo\17973904-12dd-4d61-94d9-456471fdea38\scratchpad'
w,t=pickle.load(open(SP+r'\world.pkl','rb'))
from dataset_v2.contracts import instant
scans=[n for n in w.of_kind('ScanEvent') if n.properties.get('calibrated') and n.properties.get('measured_weight_kg') is not None and n.properties.get('holdout_group') in t]
for recipe in ('different_weight','declared_weight_wrong'):
    same_ship_ok=same_scale_ok=same_scale_bad=0; multi=0; light=0
    for sid,r in t.items():
        if r['recipe']!=recipe: continue
        pk=w.nodes[sid].properties['package_ids']
        if len(pk)>1: multi+=1
        bad=[s for s in scans if s.properties['package_id']==pk[0] and abs(s.properties['measured_weight_kg']-w.nodes[pk[0]].properties['weight_kg'])>1e-9]
        if not bad: continue
        b=bad[0]; when=instant(b.properties['occurred_at']); dev=b.properties['device_ref']
        if abs(b.properties['measured_weight_kg']-w.nodes[pk[0]].properties['weight_kg'])<=.5: light+=1
        for s in scans:
            if s.id==b.id or s.properties['device_ref']!=dev or abs((instant(s.properties['occurred_at'])-when).total_seconds())>2*3600: continue
            ok=abs(s.properties['measured_weight_kg']-w.nodes[s.properties['package_id']].properties['weight_kg'])<1e-9
            if s.properties['holdout_group']==sid: same_ship_ok+=ok
            else:
                same_scale_ok+=ok; same_scale_bad+=not ok
    print(recipe,'shipments',sum(1 for r in t.values() if r['recipe']==recipe),'multi-package',multi,'within-tolerance (never flagged)',light,
          '| same-shipment packages read correctly',same_ship_ok,'| other shipments same scale +-2h: correct',same_scale_ok,'wrong',same_scale_bad)
# conflicting custody alternate vehicle
for sid,r in t.items():
    if r['recipe']!='conflicting_custody_sources': continue
    loads=[c for c in w.owned(sid,'CustodyEvent') if c.properties['event_type']=='LOADED' and 'handover-report' in str(c.properties.get('source_ref'))]
    vs=[w.nodes[c.properties['to_id']].properties for c in loads]
    print('conflicting', sid, r['split'], 'dest', w.nodes[sid].properties['destination_city'], 'vehicles base:', [(v.get('base_city'),v['type_id'][-3:],v.get('ownership')) for v in vs], 'alt has assignment:', [c.properties.get('assignment_id') is not None for c in loads])
# contractor recipes on employee drivers
for sid,r in t.items():
    if r['recipe'].startswith('contractor_') :
        lm=[a for a in w.owned(sid,'VehicleAssignment') if a.properties['mode']=='last_mile']
        emp=w.nodes[lm[0].properties['driver_id']].properties.get('employment') if lm else None
        if emp!='INDEPENDENT': print('contractor recipe on non-independent driver:',sid,r['recipe'],r['split'],emp,w.nodes[sid].properties['handling'])
# later_hub_departure plan leak: assignment valid_from vs planned milestone
for sid,r in t.items():
    if r['recipe']!='later_hub_departure': continue
    ems={(e.properties['predicate'],w.nodes[e.properties['location_id']].kind if e.properties['location_id'] in w.nodes else 'X'):instant(e.properties['earliest_at'])+timedelta(minutes=15) for e in w.owned(sid,'ExpectedMilestone')}
    out=[]
    for a in w.owned(sid,'VehicleAssignment'):
        key=('LOADED','Hub') if a.properties['mode']=='linehaul' else ('LOADED','DeliveryDepot')
        out.append((a.properties['mode'], round((instant(a.properties['valid_from'])-ems[key]).total_seconds()/3600,1), a.properties.get('session_id','') and a.properties['session_id'].rsplit('-',2)[-2:]))
    print('later_hub', sid, r['split'], 'assignment start minus planned load (h):', out)
