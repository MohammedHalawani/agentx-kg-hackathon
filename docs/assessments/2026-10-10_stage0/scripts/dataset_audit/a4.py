import pickle,collections,sys,json
from datetime import timedelta
sys.path.insert(0,'.')
SP=r'C:\Users\fbass\AppData\Local\Temp\claude\C--Projects-demo\17973904-12dd-4d61-94d9-456471fdea38\scratchpad'
o=json.load(open(SP+r'\open.json'))
def norm(v):
    v=dict(v); v['depot_hh']='silent' if str(v.get('depot_hh','')).startswith('silent') else v.get('depot_hh')
    if 'driver_app' in v: v['driver_app']='silent' if v['driver_app'].startswith('silent') else v['driver_app']
    v.pop('max_lag_min',None); v.pop('reports',None); v.pop('gps',None)
    return v
groups=collections.defaultdict(list)
for sid,r in o.items():
    if not r['open']: continue
    k=json.dumps({'codes':r['codes'],'sym':r['symptoms'],**norm(r['vec'])},sort_keys=True)
    groups[k].append(r)
ceiling=0; total=0; amb=[]
for k,rows in groups.items():
    causes=collections.Counter(c for r in rows for c in r['acc'])
    best,cover=max(causes.items(), key=lambda x:x[1])
    covered=sum(1 for r in rows if best in r['acc'])
    ceiling+=covered; total+=len(rows)
    if covered<len(rows):
        amb.append((len(rows)-covered,[ (r['recipe'],tuple(r['acc'])) for r in rows], best))
print('ceiling',ceiling,'of',total, round(ceiling/total,3))
for a in amb: print(a)
