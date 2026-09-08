"""Offline status-row and popup repair, applied after the credited English build."""
import argparse
from collections import Counter
import json
import os
import re
from pathlib import Path
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import build_catalog as bc
BASE = '048ab7108d911f15be6cd1e1751b489c645a70c2c32ac7c59962fea08116d3aa'

def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def write(p, data):
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')

def render():
    original = Image.open(HERE/'source/spr_p_0.png').convert('RGBA')
    assert original.size == (317,81)
    colors = Counter(map(tuple,np.asarray(original).reshape(-1,4).tolist()))
    opaque = [(rgba,n) for rgba,n in colors.most_common() if rgba[3]==255]
    fill, outline = opaque[0][0], opaque[1][0]
    assert fill[0]>200 and fill[2]>100 and outline[0]<100, opaque[:2]
    factor = 4
    layer = Image.new('RGBA', (317*factor,81*factor))
    draw = ImageDraw.Draw(layer)
    target = 'Virginity Lost'
    for size in range(76,29,-1):
        font = ImageFont.truetype('C:/Windows/Fonts/bahnschrift.ttf',size*factor)
        font.set_variation_by_name('SemiBold Condensed')
        bounds = draw.textbbox((0,0),target,font=font,stroke_width=3*factor)
        width,height = bounds[2]-bounds[0],bounds[3]-bounds[1]
        if width<=(317-8)*factor and height<=(81-8)*factor: break
    else: raise AssertionError('Popup needs a typography review')
    x=(layer.width-width)/2-bounds[0]
    y=(layer.height-height)/2-bounds[1]
    draw.text((x,y),target,font=font,fill=fill,stroke_width=3*factor,stroke_fill=outline)
    edited=layer.resize(original.size,Image.Resampling.LANCZOS)
    out=HERE/'english';out.mkdir(exist_ok=True)
    edited.save(out/'spr_p_0.png')
    preview=Image.new('RGBA',(317*2,81*2),(28,23,19,255))
    preview.alpha_composite(edited.resize(preview.size,Image.Resampling.NEAREST))
    preview.convert('RGB').save(HERE/'popup-preview.png')
    record={'sprite':'spr_p','source':'処女喪失','target':target,'size':size,
            'font':'Bahnschrift SemiBold Condensed','fill':fill,'outline':outline,
            'dimensions':list(edited.size),'output_sha256':bc.gmtt.sha256(out/'spr_p_0.png')}
    write(HERE/'popup-translation.json',record)
    return edited

def audit():
    snapshot=read(bc.PROJECT/'source/snapshot.json')
    font=next(f for f in snapshot['fonts'] if f['name']=='font_2')
    catalog=read(bc.ROOT/'build/catalog.en.json')
    labels=[e for e in catalog['entries'] if e['id']=='CODE:285:47']
    assert len(labels)==1
    label=labels[0]['translation']
    names=[e['translation'] for e in catalog['entries'] if e.get('code_name')=='gml_GlobalScript_scr_enemy_name']
    names.append('Virgin')
    measure=lambda s:bc.gmtt.font_measure(s,font)['line_widths'][0]
    layout=(HERE/'gml_Object_obj_state_Draw_0.gml').read_text(encoding='utf-8')
    left,top=map(int,re.search(r'draw_text\((\d+), (\d+), string_copy\(geo_text,',layout).groups())
    right=int(re.search(r'draw_text\((\d+), tmp_partner_y, tmp_partner\)',layout)[1])
    gap=int(re.search(r'string_width\(tmp_label\) \+ (\d+) \+',layout)[1])
    assert 'tmp_label_y -= tmp_line_height * 0.5;' in layout
    assert 'tmp_partner_y += tmp_line_height * 0.5;' in layout
    line=font['line_height']; label_width=measure(label)
    assert line==38 and len(names)==61
    rows=[]
    for name in names:
        width=measure(name)
        stacked=label_width+gap+width>right-left
        label_y=top+8*line-(line/2 if stacked else 0)
        value_y=top+8*line+(line/2 if stacked else 0)
        assert width<=right-left and label_width<=right-left
        assert label_y>=top+7*line+16  # retain a gap after the last counter row
        assert value_y+line<=302+444-20  # fit inside the actual plate
        if stacked: assert label_y+line<=value_y
        else: assert right-width-(left+label_width)>=gap
        rows.append({'name':name,'width':width,'stacked':stacked,'label_y':label_y,
                     'value_y':value_y,'right_edge':right,'font':'font_2'})
    assert any(r['name']=='Corrupted Soldier' and r['stacked'] for r in rows)
    report={'checked_names':len(rows),'distinct_names':len(set(names)),
            'stacked_variants':sum(r['stacked'] for r in rows),'remaining_collisions':0,
            'font_size_unchanged':True,'rows':rows}
    write(HERE/'status-audit.json',report)
    return report

def build(input_path,output,expected_input_sha256=BASE):
    assert input_path.is_file() and not output.exists()
    assert bc.gmtt.sha256(input_path)==expected_input_sha256, 'Input must match the preceding credited-build receipt'
    output.parent.mkdir(parents=True,exist_ok=True)
    edited=render(); audit_report=audit()
    before=bc.gmtt.snapshot(input_path)
    # A fresh full rebuild can contain subsequently edited manual text. Require
    # its exact upstream receipt hash and the current canonical text before import.
    input_sites=bc.gmtt.site_map(before)
    canonical=read(bc.ROOT/'build/catalog.en.json')
    assert all(input_sites[e['id']]['source']==bc.gmtt.restore(e['translation'],e['tokens']) for e in canonical['entries'])
    assert input_sites['GEN8:display_name']['source']=='Nightfall Princess | Translated by len'
    intermediate=output.with_suffix('.status-layout.win')
    assert not intermediate.exists()
    env=os.environ.copy()
    env['NFP_STATE_GML']=str(HERE/'gml_Object_obj_state_Draw_0.gml')
    bc.gmtt.run_utmt(['load',input_path.resolve(),'-s',HERE/'import_state.csx','-o',intermediate.resolve()],env,HERE/'compile.log')
    row=next(r for r in read(HERE/'source/manifest.json') if r['sprite']=='spr_p')
    assert row['source'][2:]==row['target'][2:]==row['bounding']==[317,81]
    atlas=Image.open(HERE/f"source/atlases/{row['page']}.png").convert('RGBA')
    old=np.asarray(atlas).copy()
    x,y,w,h=row['source']
    original=Image.open(HERE/'source/spr_p_0.png').convert('RGBA')
    assert np.array_equal(np.asarray(atlas.crop((x,y,x+w,y+h))),np.asarray(original))
    atlas.paste(edited,(x,y))
    pixels=np.any(np.asarray(atlas)!=old,axis=2)
    mask=np.zeros(pixels.shape,dtype=bool);mask[y:y+h,x:x+w]=True
    assert not np.any(pixels & ~mask)
    atlas_path=HERE/'popup-atlas.png';atlas.save(atlas_path)
    request=HERE/'import-request.json'
    write(request,{'mode':'import','directory':str(HERE),'pages':[{'page':row['page'],'file':str(atlas_path)}],'remaps':[]})
    env['NFP_IMAGE_REQUEST']=str(request)
    bc.gmtt.run_utmt(['load',intermediate.resolve(),'-s',bc.ROOT/'images/assets.csx','-o',output.resolve()],env,HERE/'import.log')
    after=bc.gmtt.snapshot(output)
    assert before['strings']==after['strings'][:len(before['strings'])]
    assert len(before['code'])==len(after['code'])
    changed=[]
    for a,b in zip(before['code'],after['code']):
        if a!=b:
            assert a['name']==b['name']=='gml_Object_obj_state_Draw_0'
            changed.append(a['name'])
    assert changed==['gml_Object_obj_state_Draw_0']
    for kind,values in before['resources'].items():
        updated=after['resources'][kind]
        if values!=updated:
            assert kind in ('Variables','Functions','CodeLocals') and values==updated[:len(values)],kind
    for key in before:
        if key not in ('strings','code','resources','texture_sha256','source_sha256','source_size'):
            assert before[key]==after[key],key
    assert [i for i,(a,b) in enumerate(zip(before['texture_sha256'],after['texture_sha256'])) if a!=b]==[row['page']]
    sites=bc.gmtt.site_map(after)
    catalog=read(bc.ROOT/'build/catalog.en.json')
    assert all(sites[e['id']]['source']==bc.gmtt.restore(e['translation'],e['tokens']) for e in catalog['entries'])
    assert sites['GEN8:display_name']['source']=='Nightfall Princess | Translated by len'
    write(request,{'mode':'export','directory':str(HERE/'roundtrip'),'sprites':['spr_p','spr_state']})
    bc.gmtt.run_utmt(['load',output.resolve(),'-s',bc.ROOT/'images/assets.csx'],env,HERE/'roundtrip.log')
    assert read(HERE/'source/manifest.json')==read(HERE/'roundtrip/manifest.json')
    assert np.array_equal(np.asarray(edited),np.asarray(Image.open(HERE/'roundtrip/spr_p_0.png')))
    assert np.array_equal(np.asarray(atlas),np.asarray(Image.open(HERE/f"roundtrip/atlases/{row['page']}.png")))
    assert np.array_equal(np.asarray(Image.open(HERE/'source/spr_state_0.png')),np.asarray(Image.open(HERE/'roundtrip/spr_state_0.png')))
    report={'input_sha256':before['source_sha256'],'output_sha256':after['source_sha256'],
            'bytes':output.stat().st_size,'changed_code':changed,'changed_atlases':[row['page']],
            'translated_sites_preserved':len(catalog['entries']),'fonts_audio_save_identity_unchanged':True,
            'all_prior_code_and_unedited_pixels_preserved':True,'sprite_metadata_unchanged':True,
            'popup_text':'Virginity Lost','popup_pixel_roundtrip':True,'status_names_checked':audit_report['checked_names'],
            'runtime_tested':False}
    write(output.with_suffix(output.suffix+'.followup-report.json'),report)
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('input',type=Path,nargs='?')
    parser.add_argument('output',type=Path,nargs='?')
    parser.add_argument('--expected-input-sha256',default=BASE,
                        help='For a full rebuild, use the SHA256 from the preceding title-report.json')
    args=parser.parse_args()
    if args.input is None: render();print(json.dumps(audit(),indent=2))
    else:
        assert args.output is not None
        build(args.input,args.output,args.expected_input_sha256)
