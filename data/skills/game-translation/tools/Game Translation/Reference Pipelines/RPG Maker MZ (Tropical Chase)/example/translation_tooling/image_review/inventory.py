"""Offline image pinning: inspect originals, no replacement art or game writes.

Contact-sheet approach adapted from the stable Musi Dream image inventory.
The codec is copied from the shared Gakuen MZ reference and checked against
the shipped Utils.decryptArrayBuffer algorithm. No network or OCR service.
"""
from pathlib import Path
from collections import Counter, defaultdict
from io import BytesIO
import hashlib
import json
from PIL import Image, ImageDraw, ImageFont
import rpgmv_crypt

HERE = Path(__file__).resolve().parent
GAME = HERE.parents[1]
EXTENSIONS = {'.png_', '.rpgmvp', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.ico'}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def read_image(path, key):
    raw = path.read_bytes()
    if path.suffix.lower() in {'.png_', '.rpgmvp'}:
        assert raw[:16] == rpgmv_crypt.HEADER, path
        plain = rpgmv_crypt.decrypt(raw, key)
        assert rpgmv_crypt.encrypt(plain, key) == raw, path
    else:
        plain = raw
    return raw, plain

def family(relative):
    if relative.startswith(('img/titles', 'img/system/splash')): return '01_title_splash'
    if '/tutorial/' in relative: return '02_tutorial'
    if '/credit/' in relative: return '03_credits'
    if relative.startswith('img/pictures/event/'): return '04_event_ui'
    if relative.startswith('img/pictures/event_s/'): return '07_scene_variants'
    if relative.startswith('img/pictures/'): return '05_other_pictures'
    return '06_world_system'

def main():
    key = rpgmv_crypt.key_bytes(str(GAME))
    files = sorted(p for p in GAME.rglob('*') if p.is_file()
                   and 'translation_tooling' not in p.relative_to(GAME).parts
                   and p.suffix.lower() in EXTENSIONS)
    rows, seen, thumbs = [], {}, {}
    for path in files:
        relative = path.relative_to(GAME).as_posix()
        raw, plain = read_image(path, key)
        with Image.open(BytesIO(plain)) as im:
            im.load()
            rgba = im.convert('RGBA')
            alpha = rgba.getchannel('A')
            row = dict(id=len(rows), path=relative, sha256=sha(raw), decoded_sha256=sha(plain),
                       bytes=len(raw), format=im.format, width=im.width, height=im.height,
                       mode=im.mode, frames=getattr(im, 'n_frames', 1), alpha_range=alpha.getextrema(),
                       alpha_bbox=alpha.getbbox(), has_palette=im.palette is not None,
                       has_icc=bool(im.info.get('icc_profile')), group=family(relative), status='unreviewed')
            row['representative_id'] = seen.setdefault(row['decoded_sha256'], row['id'])
            if row['representative_id'] == row['id']:
                if row['alpha_range'][0] < 255 and row['alpha_bbox']:
                    rgba = rgba.crop(row['alpha_bbox'])
                rgba.thumbnail((314, 174), Image.Resampling.LANCZOS)
                thumbs[row['id']] = rgba.copy()
        rows.append(row)
    groups = defaultdict(list)
    for row in rows:
        if row['representative_id'] == row['id']: groups[row['group']].append(row)
    contact = HERE / 'contact'
    contact.mkdir(exist_ok=True)
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 13)
    sheets = []
    for group, members in sorted(groups.items()):
        for start in range(0, len(members), 20):
            batch = members[start:start+20]
            sheet = Image.new('RGB', (1280, ((len(batch)+3)//4)*216), '#e6e8eb')
            draw = ImageDraw.Draw(sheet)
            name = f'{group}_{start//20:02}.jpg'
            for index, row in enumerate(batch):
                x, y = (index%4)*320, (index//4)*216
                thumb = thumbs[row['id']]
                tile = Image.new('RGBA', thumb.size, '#777777')
                tile.alpha_composite(thumb)
                sheet.paste(tile.convert('RGB'), (x+(320-thumb.width)//2, y))
                label = f"{row['id']:03} {Path(row['path']).name}"
                draw.text((x+4,y+175), label, font=font, fill='black')
                draw.text((x+4,y+191), f"{row['width']} x {row['height']} | {row['mode']}", font=font, fill='black')
                row['contact_sheet'] = 'contact/' + name
                row['contact_cell'] = index
            sheet.save(contact/name, quality=94)
            sheets.append({'path':'contact/'+name, 'ids':[r['id'] for r in batch]})
    # Exact literal matches are evidence, not a completeness/reachability claim.
    candidates = defaultdict(list)
    for row in rows:
        rel = row['path']
        no_ext = rel.rsplit('.',1)[0]
        for prefix in ('img/pictures/', 'img/titles1/', 'img/titles2/', 'img/system/',
                       'img/tilesets/', 'img/characters/', 'img/faces/', 'img/parallaxes/',
                       'img/battlebacks1/', 'img/battlebacks2/'):
            if no_ext.startswith(prefix): candidates[no_ext[len(prefix):]].append(row['id'])
        candidates[no_ext].append(row['id'])
    refs = defaultdict(list)
    def walk(obj, location, depth=0):
        if depth > 25: return
        if isinstance(obj,str):
            for image_id in set(candidates.get(obj, [])):
                refs[image_id].append(location)
            if obj.startswith(('[','{')):
                try: nested=json.loads(obj)
                except ValueError: return
                walk(nested,location+'::<json>',depth+1)
        elif isinstance(obj,dict):
            for k,v in obj.items(): walk(v,location+'/'+str(k),depth+1)
        elif isinstance(obj,list):
            for i,v in enumerate(obj): walk(v,location+'/'+str(i),depth+1)
    for path in sorted((GAME/'data').glob('*.json')):
        walk(json.loads(path.read_bytes()),path.relative_to(GAME).as_posix())
    walk(json.loads((GAME/'img/system/RecollectionModeMZData.json').read_bytes()),'img/system/RecollectionModeMZData.json')
    plugin_source = (GAME/'js/plugins.js').read_bytes().decode('utf-8-sig')
    plugins, _ = json.JSONDecoder().raw_decode(plugin_source,plugin_source.index('['))
    for index,plugin in enumerate(plugins):
        if plugin.get('status'):walk(plugin.get('parameters',{}),f"js/plugins.js/{index}:{plugin['name']}/parameters")
    for row in rows: row['literal_references'] = refs.get(row['id'], [])
    (HERE/'inventory.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (HERE/'sheets.json').write_text(json.dumps(sheets,indent=2)+'\n',encoding='utf-8')
    summary = dict(total=len(rows),unique=len(seen),sheets=len(sheets),
                   groups=dict(Counter(r['group'] for r in rows)),
                   multiframe=[r['path'] for r in rows if r['frames'] != 1],
                   source_sha256=sha(''.join(r['path']+r['sha256'] for r in rows).encode('utf-8')))
    (HERE/'census.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__ == '__main__':main()
