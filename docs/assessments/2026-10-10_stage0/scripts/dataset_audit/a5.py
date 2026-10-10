import collections,json
SP=r'C:\Users\fbass\AppData\Local\Temp\claude\C--Projects-demo\17973904-12dd-4d61-94d9-456471fdea38\scratchpad'
o=json.load(open(SP+r'\open.json'))
KEEP=('last_corr','missing','uncorr','attempts','contacts','manifest_versions','proof_reasons','addr_versions')
def key(r, with_hb=True):
    v=r['vec']; d={k:v[k] for k in KEEP}
    d['last_corr']=sorted({tuple(x) for x in d['last_corr']}-{('DELIVERED','Customer'),('DELIVERED','Organization')}) or d['last_corr']
    d['missing']=[[a,'Recipient' if b in ('Customer','Organization') else b] for a,b in d['missing']]
    if with_hb: d['hh']='silent' if str(v.get('depot_hh','')).startswith('silent') else 'ok'
    return json.dumps({'codes':r['codes'],**d},sort_keys=True)
for with_hb in (True,False):
    groups=collections.defaultdict(list)
    for sid,r in o.items():
        if r['open']: groups[key(r,with_hb)].append(r)
    ceiling=total=0; amb=[]
    for k,rows in groups.items():
        causes=collections.Counter(c for r in rows for c in r['acc'])
        best=max(causes, key=lambda c:(causes[c],c))
        covered=sum(best in r['acc'] for r in rows); ceiling+=covered; total+=len(rows)
        if covered<len(rows):
            amb.append((len(rows)-covered, dict(collections.Counter(r['recipe']+('*' if r['secondary'] else '') for r in rows)), best))
    print('heartbeat visible' if with_hb else 'heartbeat NOT used', 'ceiling',ceiling,'/',total, round(ceiling/total,3), 'groups',len(groups))
    for a in sorted(amb,key=lambda x:-x[0]): print('   lost',a[0],a[1],'best=',a[2])
