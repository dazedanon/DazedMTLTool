import json,re,sys
from pathlib import Path
from fontTools.ttLib import TTFont
base=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(base))
import tl
units=tl.read_json(tl.STORE)['units']
f=TTFont(base/'source/fonts/mplus-1m-regular.woff');cmap=f.getBestCmap();metrics=f['hmtx'].metrics;em=f['head'].unitsPerEm
def width(s,size=26):
    s=tl.PH.sub('',s)
    return sum(metrics[cmap[ord(c)]][0] for c in s if ord(c) in cmap)*size/em
rows=[];missing=set()
for n,u in enumerate(units):
    if u['kind']!='dialogue':continue
    text=u['target'];lines=text.split('\n')
    missing.update(c for c in tl.PH.sub('',text) if not c.isspace() and ord(c) not in cmap)
    w=max(map(width,lines))
    if w>780 or len(lines)>3:rows.append({'index':n,'width':round(w,1),'rows':len(lines),'target':text,'codes':u['codes'],'sites':u['sites']})
tl.write_json(base/'reports/english_fit_candidates.json',rows)
print(json.dumps({'dialogue':sum(u['kind']=='dialogue' for u in units),'candidates':len(rows),'over_width':sum(r['width']>780 for r in rows),'over_3_rows':sum(r['rows']>3 for r in rows),'missing_glyphs':list(missing)}))
for r in rows[:12]:print(json.dumps({k:r[k] for k in ['index','width','rows','target']},ensure_ascii=False))
