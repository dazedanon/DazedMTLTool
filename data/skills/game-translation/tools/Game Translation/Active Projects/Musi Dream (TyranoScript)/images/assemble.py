"""Merge independently reviewed image families and fan out exact source duplicates."""
from pathlib import Path
import json,hashlib,shutil
from collections import Counter
from PIL import Image
ROOT=Path(__file__).resolve().parent
BLOCKED='data/bgimage/ev_Hdouga.jpg'
ORIGINAL='0427999aee3dd5e6e6cc995eca1f6cf7a1a94bdc43222a247bc103a99a12b524'
def read(name):return json.loads((ROOT/name).read_text(encoding='utf-8-sig'))
def write(name,value):(ROOT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run():
 inventory=read('inventory.json');assets=[]
 for name in ['controls_manifest.json','ui_manifest.json','title_manifest.json','web_manifest.json']:
  doc=read(name);items=doc['assets'] if isinstance(doc,dict) and 'assets'in doc else [doc] if isinstance(doc,dict) else doc
  for a in items:
   assert a['path']!=BLOCKED
   assert a['reviewed'] is True and a['status']=='rendered',(name,a['path'],'unreviewed')
   assert sha(ROOT/'source'/a['path'])==a['source_sha256']
   assert sha(ROOT/'output'/a['path'])==a['output_sha256']
   assets.append(a)
 assert len({a['path']for a in assets})==len(assets),'overlapping family ownership'
 by_path={a['path']:a for a in assets}
 by_hash={a['source_sha256']:a for a in assets}
 for r in inventory:
  if r['path']in by_path or r['sha256']not in by_hash:continue
  a=by_hash[r['sha256']];assert r['path']!=BLOCKED
  output=ROOT/'output'/r['path'];output.parent.mkdir(parents=True,exist_ok=True)
  shutil.copy2(ROOT/'output'/a['path'],output)
  copied=dict(a,path=r['path'],duplicate_of=a['path'],id=r['id'])
  with Image.open(ROOT/'source'/r['path'])as im:assert im.size==(a['width'],a['height'])and im.mode==a['mode']
  by_path[r['path']]=copied;assets.append(copied)
 census=read('census_head.json')['rows']+read('census_tail.json')['rows']
 assert sorted(r['id']for r in census)==list(range(len(inventory)))
 by_id={r['id']:r for r in census}
 for r in census:
  if r['path']in by_path:r.update(classification='translated',review_status='rendered_and_reviewed',output_sha256=by_path[r['path']]['output_sha256'])
  elif r['path']==BLOCKED:r.update(classification='blocked_content',review_status='excluded')
 for r in census:
  if r['classification']=='duplicate_inherit':
   original=by_id[r['representative_id']]
   assert r['sha256']==original['sha256']
   r['classification']=original['classification']
   r['duplicate_review_from']=original['id']
 unresolved=[r for r in census if r['classification']not in ('translated','already_english','no_translatable_text','blocked_content')]
 assert not unresolved,[(r['id'],r['path'],r['classification'])for r in unresolved]
 limitations=['One image, data/bgimage/ev_Hdouga.jpg, remains unchanged because it contains sexual depictions explicitly labeled as minors.']
 report={'images_in_archive':len(inventory),'unique_images':len({r['sha256']for r in inventory}),'manually_rendered_images':len(assets)-sum('duplicate_of'in a for a in assets),'localized_image_entries':len(assets),'classification_counts':dict(Counter(r['classification']for r in census)),'limitations':limitations,'rows':census}
 write('coverage.json',report)
 write('manifest.json',{'format_version':1,'original_archive_sha256':ORIGINAL,'method':'Manual offline transcription, translation and local PIL lettering; no APIs.','inventory_status':'visually_reviewed_with_documented_exclusion','coverage_ref':'images/coverage.json','limitations':limitations,'assets':sorted(assets,key=lambda a:a['path'])})
 print(json.dumps({k:v for k,v in report.items()if k!='rows'},indent=2))
if __name__=='__main__':run()
