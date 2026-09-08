"""Offline visual census of pristine ASAR image assets; no OCR/network calls."""
from pathlib import Path
import hashlib,json,sys
from collections import Counter
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'scripts'))
from unpack_app import read_header,iter_entries,IMAGE_SUFFIXES

def run():
    archive=ROOT.parents[1]/'resources/app.asar.original'
    header,offset=read_header(archive)
    entries=sorted((p,e) for p,e in iter_entries(header) if Path(p).suffix.lower() in IMAGE_SUFFIXES)
    rows=[]; unique={}
    with archive.open('rb') as fh:
        for i,(rel,e) in enumerate(entries):
            fh.seek(offset+int(e['offset'])); data=fh.read(e['size'])
            dst=ROOT/'source'/rel; dst.parent.mkdir(parents=True,exist_ok=True)
            if dst.exists(): assert dst.read_bytes()==data
            else: dst.write_bytes(data)
            sha=hashlib.sha256(data).hexdigest()
            row=dict(id=i,path=rel,sha256=sha,bytes=len(data),review_status='pending')
            try:
                with Image.open(dst) as im:
                    row.update(width=im.width,height=im.height,mode=im.mode,format=im.format,frames=getattr(im,'n_frames',1))
                    rgba=im.convert('RGBA'); row['alpha_range']=rgba.getchannel('A').getextrema()
                    row['ink_bbox']=rgba.getchannel('A').getbbox()
            except Exception as exc: row['error']=str(exc)
            row['representative_id']=unique.setdefault(sha,i)
            rows.append(row)
    (ROOT/'inventory.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    reps=[r for r in rows if r['representative_id']==r['id'] and 'error' not in r]
    out=ROOT/'contact'; out.mkdir(exist_ok=True)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',13)
    for group in range((len(reps)+23)//24):
        batch=reps[group*24:(group+1)*24]
        sheet=Image.new('RGB',(1200,1040),(225,225,225)); d=ImageDraw.Draw(sheet)
        for j,row in enumerate(batch):
            x=(j%4)*300;y=(j//4)*173
            with Image.open(ROOT/'source'/row['path']) as orig:
                im=orig.convert('RGBA')
                if row['alpha_range'][0]<255 and row['ink_bbox']: im=im.crop(row['ink_bbox'])
                im.thumbnail((294,139))
                tile=Image.new('RGBA',im.size,(130,130,130,255));tile.alpha_composite(im)
                sheet.paste(tile.convert('RGB'),(x+(300-im.width)//2,y))
            label=f"{row['id']:03} {Path(row['path']).name}"
            d.text((x+3,y+140),label,font=font,fill='black')
            d.text((x+3,y+155),f"{row['width']}x{row['height']} {row['mode']}",font=font,fill='black')
        sheet.save(out/f'sheet_{group:02}.jpg',quality=95)
    print(json.dumps(dict(total=len(rows),unique=len(reps),sheets=(len(reps)+23)//24,formats=dict(Counter(r.get('format','error') for r in rows)),errors=[r for r in rows if 'error' in r]),indent=2))

if __name__=='__main__': run()
