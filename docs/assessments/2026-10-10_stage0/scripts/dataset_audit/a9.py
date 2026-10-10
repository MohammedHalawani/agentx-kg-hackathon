import pickle,collections,sys,json
sys.path.insert(0,'.')
SP=r'C:\Users\fbass\AppData\Local\Temp\claude\C--Projects-demo\17973904-12dd-4d61-94d9-456471fdea38\scratchpad'
w,t=pickle.load(open(SP+r'\world.pkl','rb'))
o=json.load(open(SP+r'\open.json'))
from dataset_v2.network import ACCEPTABLE, ROOT_CAUSE, LIVE_ABNORMAL
RULE={'BARCODE_MISMATCH','WEIGHT_MISMATCH','CONFLICTING_CUSTODY','CUSTODY_GAP','MANIFEST_CONFLICT','MISSED_MILESTONE','JOURNEY_DELAY','ADDRESS_CONFLICT','WRONG_GATE','RECIPIENT_UNAVAILABLE','DELIVERY_DISPUTE','PROOF_INSUFFICIENT','UNRECONCILED_CUSTODY','TRAFFIC_DELAY','INSUFFICIENT_EVIDENCE'}
allc=set(ROOT_CAUSE.values())|{c for s in ACCEPTABLE.values() for c in s}
print('truth cause vocabulary:',sorted(allc)); print('  not a derive.py rule code:',sorted(allc-RULE))
print(f"{'recipe':30s} {'acceptable':45s} {'codes@open (all splits, primary only)':45s} full-story codes fired but NOT acceptable")
for r in sorted(LIVE_ABNORMAL):
    rows=[(sid,x) for sid,x in t.items() if x['recipe']==r and not x.get('secondary_issue')]
    acc=sorted(ACCEPTABLE.get(r,{ROOT_CAUSE[r]}))
    full=collections.Counter(c for sid,_ in rows for c in w.gold[sid]['assessment']['supported_codes'])
    atopen=collections.Counter(c for sid,_ in rows if sid in o and o[sid]['open'] for c in o[sid]['codes'])
    n=len(rows)
    notacc={c:f'{v}/{n}' for c,v in full.items() if c not in acc}
    print(f"{r:30s} {','.join(acc):45s} {','.join(f'{c}:{v}' for c,v in atopen.items()):45s} {notacc}")
