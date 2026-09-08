"""Join reviewed image proofs without claiming unused template art was played."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(rel):return json.loads((ROOT/rel).read_text(encoding='utf8'))
manifest=read('images/manifest.json');decode=read('reports/image_decode.json')
visible=read('reports/image_visible.json');review=read('images/runtime_review.json')
archive_hash=decode['archive_sha256'];manifest_hash=sha(ROOT/'images/manifest.json')
assert decode['passed'] and decode['image_manifest_sha256']==manifest_hash
assert archive_hash==sha(ROOT/'test_game/resources/app.asar')
assert review['archive_sha256']==archive_hash and review['image_manifest_sha256']==manifest_hash
assert visible['archive_sha256']==archive_hash and not visible['exceptions']
assert visible['observations'][0]['scenario']==visible['last_state']['scenario']=='title_screen.ks'
scenes=sorted({x['scenario']for x in visible['observations']if x['scenario'].startswith('scene')})
assert len(scenes)==9
proofs=['reports/image_decode.json','reports/image_visible.json','reports/image_browser.json',
        'reports/image_targeted.json','reports/image_menus.json','reports/final_smoke.json']
for rel in proofs:
 d=read(rel);assert d['archive_sha256']==archive_hash
 if rel!='reports/image_visible.json':assert d['passed']
for s in review['screenshots']:
 assert s['reviewed'] and sha(ROOT/s['file'])==s['sha256']
observed={p for s in review['screenshots']for p in s.get('assets',[])}
all_paths={x['path']for x in manifest['assets']}
assert observed<=all_paths and len(observed)==14
assert {x['path']for x in decode['assets']}==all_paths and all(x['passed']for x in decode['assets'])
report={'passed':True,'archive_sha256':archive_hash,'image_manifest_sha256':manifest_hash,
 'method':'Manual offline image translation, local raster lettering, source/output visual review and isolated game QA.',
 'decoded_images':len(all_paths),'scene_display_images':len(observed),
 'normal_playthrough':{'scenarios':scenes,'new_game_to_title':True,'runtime_exceptions':0},
 'scene_display_paths':sorted(observed),
 'other_shipped_assets':{'count':len(all_paths-observed),'paths':sorted(all_paths-observed),
   'scope':'Unused stock/template art, alternate tutorial and speed-button images: native decode and source/output visual review; no claim of active scene usage.'},
 'native_decode_comparison':decode['comparison'],
 'targeted_fixture_scope':read('reports/image_targeted.json')['fixture_entry'],
 'visual_review':{'file':'images/runtime_review.json','sha256':sha(ROOT/'images/runtime_review.json')},
 'proofs':{x:sha(ROOT/x)for x in proofs},'limitations':manifest['limitations']}
(ROOT/'reports/image_runtime.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps({'passed':True,'decoded':len(all_paths),'visible':len(observed),'other':len(all_paths-observed)}))
