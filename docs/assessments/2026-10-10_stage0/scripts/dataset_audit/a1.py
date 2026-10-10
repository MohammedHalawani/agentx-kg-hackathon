import pickle,collections,sys
sys.path.insert(0,'.')
w,t=pickle.load(open(r'C:\Users\fbass\AppData\Local\Temp\claude\C--Projects-demo\17973904-12dd-4d61-94d9-456471fdea38\scratchpad\world.pkl','rb'))
from dataset_v2.network import LIVE_NORMAL, LIVE_ABNORMAL
print('n normal recipes',len(LIVE_NORMAL),'n abnormal',len(LIVE_ABNORMAL))
dev={s:r for s,r in t.items() if r['split']=='development'}
c=collections.Counter(r['recipe'] for r in dev.values())
print('dev recipes:',len(c))
for k,v in sorted(c.items(), key=lambda x:(x[0] in LIVE_NORMAL, -x[1], x[0])):
    rows=[r for r in dev.values() if r['recipe']==k]
    print(f"  {'N' if k in LIVE_NORMAL else 'A'} {k:32s} {v:3d}  healthy_after={sum(r['healthy'] for r in rows)} secondary={sum(1 for r in rows if r.get('secondary_issue'))} outage_aff={sum(1 for r in rows if r.get('outage_affected_event_ids'))}")
print('dev healthy', sum(r['healthy'] for r in dev.values()), 'abnormal', sum(not r['healthy'] for r in dev.values()))
# all splits
for split in ('history','development','held_out'):
    rows=[r for r in t.values() if r['split']==split]
    print(split, len(rows), 'abnormal recipes', sum(r['recipe'] in LIVE_ABNORMAL for r in rows), 'abnormal after outage', sum(not r['healthy'] for r in rows), 'secondary_effect', sum(1 for r in rows if r.get('secondary_effect_of')))
