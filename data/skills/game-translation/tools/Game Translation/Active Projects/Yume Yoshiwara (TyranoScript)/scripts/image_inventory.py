"""Inventory extracted originals and create a local browser for manual review.
Never decodes, redraws, translates, or sends an image to an API.
"""
import csv
import json
import sys
from pathlib import Path
from unpack_app import read_header,iter_entries,IMAGE_SUFFIXES,safe_join

game=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[2]
archive=game/'resources/app.asar'
images=game/'images_for_review'
header,offset=read_header(archive)
rows=[]
previous={}
if (images/'manifest.csv').exists():
    with (images/'manifest.csv').open(encoding='utf-8-sig',newline='') as fh:
        previous={row['path']:row for row in csv.DictReader(fh)}
for rel,e in iter_entries(header):
    if not rel.lower().endswith(IMAGE_SUFFIXES):continue
    out=safe_join(images,rel)
    if not out.is_file() or out.stat().st_size!=e['size']:
        raise ValueError(f'missing or incomplete extracted image: {rel}')
    prior=previous.get(rel,{})
    rows.append({'path':rel,'bytes':e['size'],'review_status':prior.get('review_status','unreviewed'),'notes':prior.get('notes','')})
rows.sort(key=lambda x:x['path'])
with (images/'manifest.csv').open('w',encoding='utf-8-sig',newline='') as fh:
    writer=csv.DictWriter(fh,fieldnames=['path','bytes','review_status','notes']);writer.writeheader();writer.writerows(rows)
data=json.dumps([{'path':x['path'],'bytes':x['bytes']} for x in rows],ensure_ascii=False).replace('<','\\u003c')
page='''<!doctype html><meta charset="utf-8"><title>Yume Yoshiwara — Original Images</title>
<style>body{font:16px system-ui;background:#202124;color:#eee;margin:24px}input{font:inherit;padding:10px;width:min(700px,90%)}button{font:inherit;padding:10px}a{color:#9dc8ff}#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px;margin-top:20px}article{background:#303134;padding:12px;overflow-wrap:anywhere}img{width:100%;height:180px;object-fit:contain;background:repeating-conic-gradient(#ddd 0% 25%,#aaa 0% 50%) 50%/16px 16px}small{display:block;margin-top:8px}</style>
<h1>Original images for manual review</h1><p>Original files and filenames. Click an image to open it at full size. No image has been translated or edited.</p>
<input id="search" placeholder="Filter by path, e.g. data/image or status"><p id="count"></p><div id="grid"></div><button id="more">Show more</button>
<script>const files=DATA;let limit=100;const q=document.querySelector('#search'),grid=document.querySelector('#grid');
function draw(){const list=files.filter(f=>f.path.toLowerCase().includes(q.value.toLowerCase()));grid.replaceChildren();document.querySelector('#count').textContent=`${list.length} matching files / ${files.length} total`;for(const f of list.slice(0,limit)){const card=document.createElement('article'),a=document.createElement('a'),caption=document.createElement('small');a.href=f.path.split('/').map(encodeURIComponent).join('/');a.target='_blank';if(/\\.(png|jpe?g|gif|webp|bmp|svg|ico)$/i.test(f.path)){const img=document.createElement('img');img.src=a.href;img.loading='lazy';img.alt=f.path;a.append(img)}else{a.textContent='Open original artwork'}caption.textContent=f.path+' — '+(f.bytes/1024).toFixed(1)+' KB';card.append(a,caption);grid.append(card)}document.querySelector('#more').hidden=limit>=list.length}
q.oninput=()=>{limit=100;draw()};document.querySelector('#more').onclick=()=>{limit+=100;draw()};draw();</script>'''.replace('DATA',data)
(images/'index.html').write_text(page,encoding='utf-8')
report={'images':len(rows),'bytes':sum(x['bytes'] for x in rows),'archive_bytes':archive.stat().st_size,
        'archive_mtime_ns':archive.stat().st_mtime_ns,'verification':'all extracted paths and lengths match ASAR entries',
        'image_processing':'none','gallery':str(images/'index.html')}
out=Path(__file__).resolve().parents[1]/'reports/images.json'
out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,indent=2))
