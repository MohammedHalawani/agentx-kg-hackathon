import json, sys
from collections import defaultdict, Counter
B = 'C:/Projects/demo/docs/evals/2026-10-09_s5/'
S = sys.argv[1]
RUNS = ['run2', 'run3', 'run4_154dd3e', 'final']
data = {r: json.load(open(B + r + '/pipeline.json'))['cases'] for r in RUNS}
rep = json.load(open(S + '/replica.json'))['shipments']

SYMPTOMS = {
    "MISSED_MILESTONE": "MILESTONE_OVERDUE", "JOURNEY_DELAY": "MILESTONE_LATE", "TRAFFIC_DELAY": "MILESTONE_LATE",
    "BARCODE_MISMATCH": "BARCODE_READ_DIFFERS", "WEIGHT_MISMATCH": "WEIGHT_READ_DIFFERS",
    "CUSTODY_GAP": "CUSTODY_TRANSFER_UNCONFIRMED", "CONFLICTING_CUSTODY": "CUSTODY_REPORTS_CONFLICT",
    "UNRECONCILED_CUSTODY": "SESSION_END_UNRECONCILED", "ADDRESS_CONFLICT": "DELIVERY_ATTEMPT_FAILED",
    "WRONG_GATE": "DELIVERY_ATTEMPT_FAILED", "RECIPIENT_UNAVAILABLE": "DELIVERY_ATTEMPT_FAILED",
    "DELIVERY_DISPUTE": "RECIPIENT_REPORTED_NOT_RECEIVED", "PROOF_INSUFFICIENT": "DELIVERY_PROOF_INCOMPLETE",
    "INSUFFICIENT_EVIDENCE": "EVIDENCE_MISSING", "MANIFEST_CONFLICT": "MANIFEST_CUSTODY_CONFLICT",
}
inv = defaultdict(set)
for c, s in SYMPTOMS.items():
    inv[s].add(c)

def ok(c):
    return c['primary_cause'] in (c['acceptable_causes'] or [])

def opening(c, r):
    # run2/run3 lack opening_symptoms: use replica opening for the first case of a shipment
    if c.get('opening_symptoms'):
        return c['opening_symptoms']
    return None

print('== 0. run-level case accuracy')
for r in RUNS:
    cs = data[r]
    print(r, sum(ok(c) for c in cs), len(cs), 'degraded', sum(bool(c['degraded']) for c in cs),
          'shipments', len({c['shipment_id'] for c in cs}))

# ---- 1. per shipment
print('\n== 1. per shipment per run (case order by opened_at; + correct, - wrong, D degraded)')
ships = sorted({c['shipment_id'] for c in data['final']})
pattern = {}
first_ok = {}
all_ok = {}
for sid in ships:
    row = []
    fo, ao = [], []
    for r in RUNS:
        cs = sorted([c for c in data[r] if c['shipment_id'] == sid], key=lambda c: c['opened_at'])
        row.append(''.join('D' if c['degraded'] else ('+' if ok(c) else '-') for c in cs))
        fo.append(ok(cs[0]))
        ao.append(all(ok(c) for c in cs))
    pattern[sid] = row
    first_ok[sid] = fo
    all_ok[sid] = ao
recipe = {c['shipment_id']: c['truth_recipe'] for c in data['final']}
acc = {c['shipment_id']: c['acceptable_causes'] for c in data['final']}
cls = {}
for sid in ships:
    n = sum(first_ok[sid])
    cls[sid] = 'always-correct' if n == 4 else 'always-wrong' if n == 0 else 'flaky'
    print(sid[-6:], recipe[sid][:28].ljust(28), ' | '.join(p.ljust(2) for p in pattern[sid]), ' first-case correct', n, '/4 ', cls[sid],
          ' all-cases', sum(all_ok[sid]), '/4')
print(Counter(cls.values()))
# classification by all-cases rule as well
cls2 = Counter('always-correct' if sum(all_ok[s]) == 4 else 'always-wrong' if sum(all_ok[s]) == 0 else 'flaky' for s in ships)
print('all-cases rule', cls2)
print('per-run shipment accuracy (first case):', [sum(first_ok[s][i] for s in ships) for i in range(4)],
      ' all cases:', [sum(all_ok[s][i] for s in ships) for i in range(4)])
# by recipe
print('\n-- by recipe')
byr = defaultdict(list)
for s in ships:
    byr[recipe[s]].append(s)
for rcp, ss in sorted(byr.items(), key=lambda x: (sum(sum(first_ok[s]) for s in x[1]) / (4 * len(x[1])), x[0])):
    tot = sum(sum(first_ok[s]) for s in ss)
    print(rcp.ljust(30), len(ss), 'shipments', tot, '/', 4 * len(ss), 'first-case correct', [cls[s] for s in ss])

# expected correct-count distribution under independence
p = sum(sum(first_ok[s]) for s in ships) / (4 * len(ships))
print('pooled p', round(p, 3))

# ---- 2. always wrong
print('\n== 2. always-wrong shipments: primary_cause per run (all cases)')
for sid in ships:
    if cls[sid] != 'always-wrong':
        continue
    pcs = []
    for r in RUNS:
        cs = sorted([c for c in data[r] if c['shipment_id'] == sid], key=lambda c: c['opened_at'])
        pcs.append('/'.join(str(c['primary_cause']) for c in cs))
    print(sid[-6:], recipe[sid], 'acc=', acc[sid], '->', pcs)
print('\n-- flaky shipments: primary_cause per run')
for sid in ships:
    if cls[sid] != 'flaky':
        continue
    pcs = []
    for r in RUNS:
        cs = sorted([c for c in data[r] if c['shipment_id'] == sid], key=lambda c: c['opened_at'])
        pcs.append('/'.join(str(c['primary_cause']) for c in cs))
    print(sid[-6:], recipe[sid], 'acc=', acc[sid], '->', pcs)

# ---- 3. symptom baseline on final
print('\n== 3. symptom-only baselines on final 41 cases')
fin = sorted(data['final'], key=lambda c: (c['shipment_id'], c['opened_at']))
def single_codes(syms):
    return [next(iter(inv[s])) for s in syms if len(inv.get(s, ())) == 1]
def b_strict(c):
    o = c['opening_symptoms']
    if len(o) == 1 and len(inv.get(o[0], ())) == 1:
        return next(iter(inv[o[0]]))
    return None
def b_specific(c):
    o = c['opening_symptoms']
    sc = [next(iter(inv[s])) for s in o if len(inv.get(s, ())) == 1 and s != 'MILESTONE_OVERDUE']
    if sc:
        return sc[0]
    if 'MILESTONE_OVERDUE' in o:
        return 'MISSED_MILESTONE'
    return None
def b_any(c):
    return set(single_codes(c['opening_symptoms']))
# rule-code baseline from replica (exact rule codes at opening, most specific first)
def rule_codes_at(sid, t):
    tl = rep[sid]['timeline']
    cur = []
    for tt, codes, sym in tl:
        if tt[:19] <= t[:19]:
            cur = codes
    return cur
def b_rule(c):
    codes = rule_codes_at(c['shipment_id'], c['opened_at'])
    spec = [x for x in codes if x != 'MISSED_MILESTONE']
    if spec:
        return spec[0]
    return 'MISSED_MILESTONE' if codes else None
res = defaultdict(lambda: [0, 0])
rows = []
for c in fin:
    a = set(c['acceptable_causes'])
    s1, s2, s3, s4 = b_strict(c), b_specific(c), b_any(c), b_rule(c)
    r = {'agent': ok(c), 'strict': s1 in a, 'specific': s2 in a, 'any_oracle': bool(s3 & a), 'rulecode': s4 in a}
    for k, v in r.items():
        res[k][0] += v
        res[k][1] += 1
    rows.append((c['shipment_id'][-6:], c['truth_recipe'][:24], ','.join(c['opening_symptoms']), c['primary_cause'], s2, s4, r))
for row in rows:
    print(row[0], row[1].ljust(24), row[2][:55].ljust(55), 'agent', str(row[3])[:20].ljust(20), 'B_spec', str(row[4])[:20].ljust(20), 'B_rule', str(row[5])[:20].ljust(20),
          ''.join('+' if row[6][k] else '-' for k in ('agent', 'strict', 'specific', 'any_oracle', 'rulecode')))
print({k: v for k, v in res.items()})
nd = [c for c in fin if not c['degraded']]
print('non-degraded n', len(nd), 'agent', sum(ok(c) for c in nd), 'B_spec', sum(b_specific(c) in c['acceptable_causes'] for c in nd),
      'B_rule', sum(b_rule(c) in c['acceptable_causes'] for c in nd))
# agreement matrix agent vs B_spec
m = Counter((ok(c), b_specific(c) in c['acceptable_causes']) for c in fin)
print('agent x B_spec', m)
m = Counter((ok(c), b_rule(c) in c['acceptable_causes']) for c in fin)
print('agent x B_rule', m)
# agent equal to baseline
print('agent==B_spec', sum(c['primary_cause'] == b_specific(c) for c in fin), 'agent==B_rule', sum(c['primary_cause'] == b_rule(c) for c in fin))
# same baselines across runs (run4 has opening symptoms)
for r in ['run4_154dd3e']:
    cs = data[r]
    print(r, 'agent', sum(ok(c) for c in cs), 'B_spec', sum(b_specific(c) in c['acceptable_causes'] for c in cs), 'B_rule', sum(b_rule(c) in c['acceptable_causes'] for c in cs), len(cs))

# ---- 4. ambiguity
print('\n== 4. ambiguity by opening symptom set (final case rows)')
groups = defaultdict(list)
for c in fin:
    groups[tuple(c['opening_symptoms'])].append(c)
amb = {}
for k, cs in sorted(groups.items(), key=lambda x: -len(x[1])):
    causes = Counter(c['truth_cause'] for c in cs)
    recipes = Counter(c['truth_recipe'] for c in cs)
    inter = set.intersection(*[set(c['acceptable_causes']) for c in cs])
    best = max(((lab, sum(lab in c['acceptable_causes'] for c in cs)) for lab in {l for c in cs for l in c['acceptable_causes']}), key=lambda x: x[1])
    single = len(causes) == 1
    for c in cs:
        amb[c['case_id']] = single
    print(len(cs), 'cases', k, 'distinct truth_cause', len(causes), dict(causes), '| common acceptable', sorted(inter), '| best label', best,
          '| agent', sum(ok(c) for c in cs))
for lab, val in (('single-cause', True), ('ambiguous', False)):
    cs = [c for c in fin if amb[c['case_id']] == val]
    print(lab, 'cases', len(cs), 'agent correct', sum(ok(c) for c in cs), 'B_spec', sum(b_specific(c) in c['acceptable_causes'] for c in cs),
          'B_rule', sum(b_rule(c) in c['acceptable_causes'] for c in cs), 'degraded', sum(bool(c['degraded']) for c in cs))
# best symptom-only classifier (in-sample upper bound)
ub = sum(max(sum(lab in c['acceptable_causes'] for c in cs) for lab in {l for c in cs for l in c['acceptable_causes']}) for cs in groups.values())
print('in-sample best deterministic symptom-set->label classifier (upper bound):', ub, '/', len(fin))
