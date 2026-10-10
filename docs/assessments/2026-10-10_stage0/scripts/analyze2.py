import json, sys
from collections import defaultdict, Counter
B = 'C:/Projects/demo/docs/evals/2026-10-09_s5/'
S = sys.argv[1]
RUNS = ['run2', 'run3', 'run4_154dd3e', 'final']
data = {r: json.load(open(B + r + '/pipeline.json'))['cases'] for r in RUNS}
rep = json.load(open(S + '/replica.json'))['shipments']
def ok(c): return c['primary_cause'] in (c['acceptable_causes'] or [])

print('== reviewer verdict x correctness (final review of last round)')
for r in RUNS:
    t = Counter((c['review'], ok(c)) for c in data[r])
    rounds = Counter((c['review_rounds'], c['review'], ok(c)) for c in data[r])
    acc_wrong = sum(1 for c in data[r] if c['review'] == 'ACCEPT' and not ok(c))
    acc_all = sum(1 for c in data[r] if c['review'] == 'ACCEPT')
    rev_right = sum(1 for c in data[r] if c['review'] == 'REVISE' and ok(c))
    rev_all = sum(1 for c in data[r] if c['review'] == 'REVISE')
    print(r, dict(t), '| ACCEPT precision', acc_all - acc_wrong, '/', acc_all, '| REVISE-final on correct', rev_right, '/', rev_all)
    print('   rounds', dict(rounds))
# pooled
allc = [c for r in RUNS for c in data[r]]
print('pooled ACCEPT', sum(c['review'] == 'ACCEPT' for c in allc), 'of which correct', sum(c['review'] == 'ACCEPT' and ok(c) for c in allc))
print('pooled REVISE(final)', sum(c['review'] == 'REVISE' for c in allc), 'of which correct', sum(c['review'] == 'REVISE' and ok(c) for c in allc))
print('pooled 2-round & ACCEPT', sum(c['review_rounds'] == 2 and c['review'] == 'ACCEPT' for c in allc), 'correct', sum(c['review_rounds'] == 2 and c['review'] == 'ACCEPT' and ok(c) for c in allc))
# accuracy among non-degraded by review
print('pooled REVISE by recommended action', Counter((c['recommended_action'], ok(c)) for c in allc if c['review'] == 'REVISE'))
print('final REVISE by recipe', [(c['shipment_id'][-6:], c['truth_recipe'], c['primary_cause'], c['recommended_action'], ok(c)) for c in data['final'] if c['review'] == 'REVISE'])
print('final fact_check_unsupported', Counter((c['fact_check_unsupported'], ok(c)) for c in data['final']))
print('pooled fact_check_unsupported', Counter((c['fact_check_unsupported'], ok(c)) for c in allc))

print('\n== predicted label precision (pooled over 4 runs, all cases)')
pl = defaultdict(lambda: [0, 0])
for c in allc:
    pl[c['primary_cause']][0] += ok(c); pl[c['primary_cause']][1] += 1
for k, v in sorted(pl.items(), key=lambda x: -x[1][1]):
    print(str(k).ljust(24), v[0], '/', v[1])
print('-- final only')
pl = defaultdict(lambda: [0, 0])
for c in data['final']:
    pl[c['primary_cause']][0] += ok(c); pl[c['primary_cause']][1] += 1
for k, v in sorted(pl.items(), key=lambda x: -x[1][1]):
    print(str(k).ljust(24), v[0], '/', v[1])
print('-- CUSTODY_GAP predictions when MILESTONE_OVERDUE-only opening (run4+final)')
for r in ['run4_154dd3e', 'final']:
    cs = [c for c in data[r] if c['opening_symptoms'] == ['MILESTONE_OVERDUE']]
    print(r, 'n', len(cs), Counter(c['primary_cause'] for c in cs), 'correct', sum(ok(c) for c in cs))

print('\n== device_status use vs DELAYED_SYNC-acceptable cases (first case of shipment)')
for r in RUNS:
    rows = []
    for c in sorted(data[r], key=lambda c: c['opened_at']):
        if 'DELAYED_SYNC' in (c['acceptable_causes'] or []):
            rows.append((c['shipment_id'][-6:], 'device_status' in c['tools'], c['primary_cause'], ok(c)))
    print(r, rows)
pool = [(('device_status' in c['tools']), c['primary_cause'] == 'DELAYED_SYNC') for c in allc if 'DELAYED_SYNC' in (c['acceptable_causes'] or [])]
print('pooled (device_status called, said DELAYED_SYNC):', Counter(pool))
pool2 = [(('device_status' in c['tools']), c['primary_cause'] == 'DELAYED_SYNC') for c in allc if 'DELAYED_SYNC' not in (c['acceptable_causes'] or [])]
print('pooled, non-sync shipments (device_status called, said DELAYED_SYNC):', Counter(pool2))
print('tool calls mean final', sum(c['tool_calls'] for c in data['final']) / 41, 'correct', sum(c['tool_calls'] for c in data['final'] if ok(c)) / sum(ok(c) for c in data['final']),
      'wrong', sum(c['tool_calls'] for c in data['final'] if not ok(c)) / sum(not ok(c) for c in data['final']))
print('tool usage final', Counter(t for c in data['final'] for t in set(c['tools'])))

print('\n== run-to-run flips (first case per shipment)')
def first(r):
    out = {}
    for c in sorted(data[r], key=lambda c: c['opened_at']):
        out.setdefault(c['shipment_id'], c)
    return out
F = {r: first(r) for r in RUNS}
for a, b in [('run2', 'run3'), ('run3', 'run4_154dd3e'), ('run4_154dd3e', 'final'), ('run2', 'final')]:
    flips = [s for s in F[a] if ok(F[a][s]) != ok(F[b][s])]
    same_label = sum(F[a][s]['primary_cause'] == F[b][s]['primary_cause'] for s in F[a])
    print(a, '->', b, 'outcome flips', len(flips), 'same primary label', same_label, '/ 39')
# label agreement across all 4 runs
agree4 = sum(len({F[r][s]['primary_cause'] for r in RUNS}) == 1 for s in F['final'])
print('shipments with identical primary label in all 4 runs', agree4, '/ 39')

print('\n== opening-symptom ambiguity over all 207 abnormal shipments in the 600-shipment world (replica)')
op = {}
for sid, v in rep.items():
    first_open = next((x for x in v['timeline'] if x[2]), None)
    if first_open is None:
        continue
    op[sid] = (tuple(first_open[2]), tuple(first_open[1]), v)
print('abnormal with an opening', len(op), 'of', len(rep), 'never opened:', [ (s[-6:], v['recipe'], v['split']) for s, v in rep.items() if s not in op])
groups = defaultdict(list)
for sid, (sym, codes, v) in op.items():
    groups[sym].append(v)
final_sets = {tuple(c['opening_symptoms']) for c in data['final']}
tot_best = 0
for sym, vs in sorted(groups.items(), key=lambda x: -len(x[1])):
    causes = Counter(v['root_cause'] for v in vs)
    labels = {l for v in vs for l in v['acceptable']}
    best = max(((l, sum(l in v['acceptable'] for v in vs)) for l in labels), key=lambda x: x[1])
    tot_best += best[1]
    print(('*' if sym in final_sets else ' '), len(vs), sym, 'distinct root causes', len(causes), dict(causes.most_common()), 'best single label', best)
print('best symptom-set->label classifier over 600-world abnormal shipments:', tot_best, '/', len(op))
# by rule-code set (what the monitor actually computed before mapping to symptoms)
g2 = defaultdict(list)
for sid, (sym, codes, v) in op.items():
    g2[codes].append(v)
tb = 0
for codes, vs in g2.items():
    labels = {l for v in vs for l in v['acceptable']}
    tb += max(sum(l in v['acceptable'] for v in vs) for l in labels)
print('best rule-code-set->label classifier:', tb, '/', len(op), 'distinct rule-code sets', len(g2), 'distinct symptom sets', len(groups))
# for final cases: ambiguity of their opening symptom set in the 600-world
amb = {}
for c in data['final']:
    vs = groups.get(tuple(c['opening_symptoms']), [])
    labels = {l for v in vs for l in v['acceptable']}
    common = set.intersection(*[set(v['acceptable']) for v in vs]) if vs else set()
    amb[c['case_id']] = (len({v['root_cause'] for v in vs}), bool(common))
for lab, f in (('determined (one label acceptable for every shipment with this opening set, 600-world)', lambda x: x[1]),
               ('ambiguous', lambda x: not x[1])):
    cs = [c for c in data['final'] if f(amb[c['case_id']])]
    print(lab, 'cases', len(cs), 'agent correct', sum(ok(c) for c in cs), 'degraded', sum(bool(c['degraded']) for c in cs))

print('\n== baselines by determined/ambiguous (600-world definition)')
INV={"MILESTONE_OVERDUE":"MISSED_MILESTONE","BARCODE_READ_DIFFERS":"BARCODE_MISMATCH","WEIGHT_READ_DIFFERS":"WEIGHT_MISMATCH","CUSTODY_TRANSFER_UNCONFIRMED":"CUSTODY_GAP","CUSTODY_REPORTS_CONFLICT":"CONFLICTING_CUSTODY","SESSION_END_UNRECONCILED":"UNRECONCILED_CUSTODY","RECIPIENT_REPORTED_NOT_RECEIVED":"DELIVERY_DISPUTE","DELIVERY_PROOF_INCOMPLETE":"PROOF_INSUFFICIENT","EVIDENCE_MISSING":"INSUFFICIENT_EVIDENCE","MANIFEST_CUSTODY_CONFLICT":"MANIFEST_CONFLICT"}
def bsym(c):
    spec=[INV[s] for s in c['opening_symptoms'] if s in INV and s!='MILESTONE_OVERDUE']
    return spec[0] if spec else ('MISSED_MILESTONE' if 'MILESTONE_OVERDUE' in c['opening_symptoms'] else None)
def brule(c):
    cur=[]
    for tt,codes,sym in rep[c['shipment_id']]['timeline']:
        if tt[:19]<=c['opened_at'][:19]: cur=codes
    sc=[x for x in cur if x!='MISSED_MILESTONE']
    return sc[0] if sc else ('MISSED_MILESTONE' if cur else None)
for lab,val in (('determined',True),('ambiguous',False)):
    cs=[c for c in data['final'] if amb[c['case_id']][1]==val]
    print(lab,len(cs),'agent',sum(ok(c) for c in cs),'B_symptom',sum(bsym(c) in c['acceptable_causes'] for c in cs),'B_rule',sum(brule(c) in c['acceptable_causes'] for c in cs),
          'wrong agent:',[(c['shipment_id'][-6:],c['primary_cause']) for c in cs if not ok(c)])
