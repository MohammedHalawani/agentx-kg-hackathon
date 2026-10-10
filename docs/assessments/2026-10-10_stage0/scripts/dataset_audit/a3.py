import pickle,collections,sys,json,statistics
from datetime import timedelta
sys.path.insert(0,'.')
SP=r'C:\Users\fbass\AppData\Local\Temp\claude\C--Projects-demo\17973904-12dd-4d61-94d9-456471fdea38\scratchpad'
w,t=pickle.load(open(SP+r'\world.pkl','rb'))
o=json.load(open(SP+r'\open.json'))
from dataset_v2.derive import assess_shipment, EvidenceIndex
from dataset_v2.contracts import instant, iso
from operations.store import DETECTION_ALLOWANCE_SECONDS as DA
from dataset_v2.feed import split_feed, reconstitute
imported, items = split_feed(w, t); full = reconstitute(imported, items)
I={'full':EvidenceIndex(full),'w':EvidenceIndex(w)}
res=collections.defaultdict(list)
for sid,r in o.items():
    if not r['open']: continue
    world,idx=(full,I['full']) if r['split']=='development' else (w,I['w'])
    acc=set(r['acc'])
    at0=instant(r['open'])
    hit_open = bool(acc & set(r['codes']))
    delay=None
    if not hit_open:
        for h in range(1,73):
            a=assess_shipment(world,sid,iso(at0+timedelta(minutes=15*h)),_index=idx,detection_allowance_seconds=DA)
            if acc & set(a['supported_codes']):
                delay=15*h/60; break
    label=r['recipe']+('+'+(r['secondary'] if r['secondary']!='offline_device_sync' else 'outage') if r['secondary'] else '')
    res[label].append((hit_open,delay,tuple(r['codes'])))
print(f"{'recipe':45s} n  acc_code@open  later(h, median)  never<18h  codes@open")
for k,v in sorted(res.items()):
    n=len(v); ho=sum(x[0] for x in v); later=[x[1] for x in v if not x[0] and x[1] is not None]; never=sum(1 for x in v if not x[0] and x[1] is None)
    codes=collections.Counter(x[2] for x in v).most_common(2)
    print(f"{k:45s} {n:2d} {ho:3d}           {len(later):2d} ({statistics.median(later) if later else '-'})        {never:3d}   {codes}")
