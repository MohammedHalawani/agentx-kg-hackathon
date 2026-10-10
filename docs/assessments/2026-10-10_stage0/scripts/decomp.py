import json, sys
from collections import Counter, defaultdict
B='C:/Projects/demo/docs/evals/2026-10-09_s5/'
RUNS=['run2','run3','run4_154dd3e','final']
data={r:json.load(open(B+r+'/pipeline.json'))['cases'] for r in RUNS}
rep=json.load(open(sys.argv[1]+'/replica.json'))['shipments']
def ok(c): return c['primary_cause'] in (c['acceptable_causes'] or [])
def cat(c):
    if ok(c): return None
    p=c['primary_cause']; r=c['truth_recipe']
    if p is None: return 'investigator degraded (no diagnosis)'
    if r=='contractor_unreturned': return 'label unobservable at snapshot (+9h)'
    if r in ('absent_session_receipt','partial_packages') and p in ('CUSTODY_GAP','MISSED_MILESTONE'): return 'defensible at snapshot; narrow/inconsistent acceptable set'
    if r=='traffic_safe_return': return 'tool gap: TrafficObservation unreachable'
    if r=='report_different_location' and p=='PROOF_INSUFFICIENT': return 'taxonomy: PROOF_INSUFFICIENT excluded for this report recipe'
    if 'DELAYED_SYNC' in c['acceptable_causes']: return 'model: missed DELAYED_SYNC (handheld silent at snapshot)'
    if p=='DELAYED_SYNC': return 'model: DELAYED_SYNC with no outage'
    return 'model: other ('+r+' -> '+p+')'
tot=Counter()
for r in RUNS:
    cnt=Counter(cat(c) for c in data[r] if not ok(c))
    tot.update(cnt)
    print(r, sum(cnt.values()), dict(cnt))
print('pooled', sum(tot.values()), dict(tot))
# grown-symptom signal: wrong cases whose final symptom set names an acceptable cause absent at opening
INV={"MILESTONE_OVERDUE":"MISSED_MILESTONE","BARCODE_READ_DIFFERS":"BARCODE_MISMATCH","WEIGHT_READ_DIFFERS":"WEIGHT_MISMATCH","CUSTODY_TRANSFER_UNCONFIRMED":"CUSTODY_GAP","CUSTODY_REPORTS_CONFLICT":"CONFLICTING_CUSTODY","SESSION_END_UNRECONCILED":"UNRECONCILED_CUSTODY","RECIPIENT_REPORTED_NOT_RECEIVED":"DELIVERY_DISPUTE","DELIVERY_PROOF_INCOMPLETE":"PROOF_INSUFFICIENT","EVIDENCE_MISSING":"INSUFFICIENT_EVIDENCE","MANIFEST_CUSTODY_CONFLICT":"MANIFEST_CONFLICT"}
g=[]
for c in data['final']:
    if ok(c): continue
    new=set(c['symptoms'])-set(c['opening_symptoms'])
    named={INV[s] for s in new if s in INV} & set(c['acceptable_causes'])
    if named: g.append((c['shipment_id'][-6:], c['truth_recipe'], sorted(new), sorted(named)))
print('final wrong cases whose later symptoms name an acceptable cause (no re-investigation):', len(g)); [print('  ',x) for x in g]
# second-cause-only credit per run
for r in RUNS:
    only=[(c['shipment_id'][-6:], c['primary_cause']) for c in data[r] if c['primary_cause']=='DELAYED_SYNC' and ok(c) and c['truth_recipe'] not in ('offline_device_sync',) and c['truth_cause']!='DELAYED_SYNC']
    print(r,'credited only by second-cause DELAYED_SYNC:', only)
# replica-based baselines for every run
def at(sid,t):
    cur=([],[])
    for tt,codes,sym in rep[sid]['timeline']:
        if tt[:19]<=t[:19]: cur=(codes,sym)
    return cur
SINGLE={s:c for s,c in INV.items()}
for r in RUNS:
    bs=br=0
    for c in data[r]:
        codes,sym=at(c['shipment_id'],c['opened_at'])
        spec=[SINGLE[s] for s in sym if s in SINGLE and s!='MILESTONE_OVERDUE']
        pred=spec[0] if spec else ('MISSED_MILESTONE' if 'MILESTONE_OVERDUE' in sym else None)
        bs+=pred in c['acceptable_causes']
        sc=[x for x in codes if x!='MISSED_MILESTONE']
        pr=sc[0] if sc else ('MISSED_MILESTONE' if codes else None)
        br+=pr in c['acceptable_causes']
    print(r,'cases',len(data[r]),'agent',sum(ok(c) for c in data[r]),'B_symptom',bs,'B_rulecode',br)
# per-shipment (first case) accuracy
for r in RUNS:
    f={}
    for c in sorted(data[r],key=lambda c:c['opened_at']): f.setdefault(c['shipment_id'],c)
    nd=[c for c in data[r] if not c['degraded']]
    print(r,'case-level',sum(ok(c) for c in data[r]),'/',len(data[r]),'first-case per shipment',sum(ok(c) for c in f.values()),'/39','excl degraded',sum(ok(c) for c in nd),'/',len(nd))
