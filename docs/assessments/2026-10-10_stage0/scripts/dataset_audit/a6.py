import pickle,collections,sys,json,re
sys.path.insert(0,'.')
SP=r'C:\Users\fbass\AppData\Local\Temp\claude\C--Projects-demo\17973904-12dd-4d61-94d9-456471fdea38\scratchpad'
w,t=pickle.load(open(SP+r'\world.pkl','rb'))
from dataset_v2.contracts import instant
from dataset_v2.network import LIVE_NORMAL
def rec(sid): return t[sid]['recipe'] if sid in t else None
def tally(pred, desc):
    c=collections.Counter()
    for n in w.nodes.values():
        sid=n.properties.get('holdout_group')
        if sid in t and pred(n): c[rec(sid)]+=1
    shipments=collections.Counter()
    seen=set()
    for n in w.nodes.values():
        sid=n.properties.get('holdout_group')
        if sid in t and pred(n) and sid not in seen: seen.add(sid); shipments[rec(sid)]+=1
    tot={r:sum(1 for x in t.values() if x['recipe']==r) for r in shipments}
    print(f'{desc}: ', {r:f'{v}/{tot[r]}' for r,v in shipments.items()})
tally(lambda n:n.id.endswith('-ACTUAL-SESSION'),'ACTUAL-SESSION node (plan data, visible at booking)')
tally(lambda n:n.kind=='AddressVersion' and n.properties.get('version')==2,'AddressVersion v2 (imported, recorded_at=start)')
tally(lambda n:n.kind=='ScanEvent' and n.properties.get('observation_type')=='DEPOT_DISPATCH_SCAN','observation_type DEPOT_DISPATCH_SCAN')
tally(lambda n:n.kind=='CustodyEvent' and 'handover-report' in str(n.properties.get('source_ref')),'source_ref *-handover-report')
tally(lambda n:n.kind=='CustodyEvent' and n.properties.get('source_quality')=='ATTRIBUTED_REPORT','CustodyEvent ATTRIBUTED_REPORT')
tally(lambda n:n.kind=='CustodyEvent' and n.properties.get('source_quality')=='INCOMPLETE_ACK','CustodyEvent INCOMPLETE_ACK')
tally(lambda n:n.kind=='Manifest' and n.properties.get('version')==2,'Manifest v2 REVISED')
tally(lambda n:n.kind=='TrafficObservation','TrafficObservation')
tally(lambda n:n.kind=='RecipientReport','RecipientReport')
tally(lambda n:n.kind=='DeliveryAttempt' and n.properties.get('observed_gate')=='Gate 1','observed_gate Gate 1')
for reason in ('RECIPIENT_NOT_REACHED','SESSION_CAPACITY_EXHAUSTED','SESSION_WINDOW_CLOSED','ACCESS_NOT_COMPLETED','CONTACT_AGREED_NEXT_ATTEMPT'):
    tally(lambda n,reason=reason:n.kind=='DeliveryAttempt' and n.properties.get('failed_reason')==reason,'failed_reason '+reason)
tally(lambda n:n.kind=='ContactAttempt' and n.properties.get('result')=='NO_RESPONSE','ContactAttempt NO_RESPONSE')
for rt in ('AUTHORIZED_ALTERNATE','UNVERIFIED_PERSON','OTHER_PERSON'):
    tally(lambda n,rt=rt:n.kind=='HandoffEvidence' and n.properties.get('recipient_type')==rt,'HandoffEvidence '+rt)
tally(lambda n:n.kind=='AuthenticationEvidence' and n.properties.get('result')=='FAIL','Auth FAIL')
tally(lambda n:n.id.split('-')[-2:-1]==['PRIOR'] or '-PRIOR-' in n.id,'PRIOR-* fixture nodes')
# barcode / weight signatures
bc=collections.Counter(); wt=collections.Counter()
for n in w.of_kind('ScanEvent'):
    p=n.properties; pkg=w.nodes.get(p.get('package_id'))
    if not pkg or p.get('holdout_group') not in t: continue
    if p.get('observed_barcode') and p['observed_barcode']!=pkg.properties['manifest_barcode']:
        bc[(rec(p['holdout_group']), p['observed_barcode']==pkg.properties['manifest_barcode']+'8', p.get('confidence'))]+=1
    if p.get('measured_weight_kg') is not None and p.get('calibrated') and abs(p['measured_weight_kg']-pkg.properties['weight_kg'])>1e-9:
        wt[(rec(p['holdout_group']), round(p['measured_weight_kg']/pkg.properties['weight_kg'],2))]+=1
print('barcode mismatches (recipe, observed==manifest+"8", confidence):',dict(bc))
print('weight mismatches (recipe, ratio):',dict(wt))
