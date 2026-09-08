"""Keep wrapped narration above the camera's bottom edge in all four consumers."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import build_catalog as bc

BASE='713a7fe971a7784e015605035aa0cd32fe4bcfe04b779ddf2346ceb8c2878076'
PATHS={f'gml_Object_obj_{name}_Draw_0':xy for name,xy in {
    'hall':(882,940),'quest':(882,940),'gallery':(882,940),'ui':(930,988)}.items()}

def build(source,output,expected=BASE):
    assert bc.gmtt.sha256(source)==expected and not output.exists()
    output.parent.mkdir(parents=True,exist_ok=True)
    export=output.parent/'input-decompiled'
    assert not export.exists()
    subprocess.run([sys.executable,str(bc.TOOLKIT/'gmtt.py'),'decompile',str(source),'-o',str(export)],check=True)
    assert bc.read(export/'manifest.json')['source_sha256']==expected
    prepared=output.parent/'gml';prepared.mkdir()
    changes=[]
    for name,(x,y) in PATHS.items():
        original=(export/'CodeEntries'/(name+'.gml')).read_text(encoding='utf-8')
        old=f'    draw_text_ext({x}, {y} - geo_text_y, scr_newline(geo_text, 789), 35, 789);'
        assert original.count(old)==1,name
        new=f'''    var tl_caption = scr_newline(geo_text, 789);
    var tl_caption_bottom = room_height - 16;
    if (view_enabled)
        tl_caption_bottom = camera_get_view_y(view_camera[0]) + camera_get_view_height(view_camera[0]) - 16;
    var tl_caption_y = min({y}, tl_caption_bottom - string_height_ext(tl_caption, 35, 789));
    draw_text_ext({x}, tl_caption_y - geo_text_y, tl_caption, 35, 789);'''
        changed=original.replace(old,new)
        assert changed.replace(new,old)==original
        path=prepared/(name+'.gml');path.write_text(changed,encoding='utf-8')
        changes.append({'name':name,'source':str(path.resolve())})
    request=output.parent/'request.json';bc.write(request,{'changes':changes})
    before=bc.gmtt.snapshot(source)
    canonical=bc.read(bc.ROOT/'build/catalog.en.json')
    wanted={e['id']:bc.gmtt.restore(e['translation'],e['tokens']) for e in canonical['entries']}
    before_sites=bc.gmtt.site_map(before)
    assert all(before_sites[k]['source']==v for k,v in wanted.items())
    env=os.environ.copy();env['NFP_NARRATION_REQUEST']=str(request.resolve())
    bc.gmtt.run_utmt(['load',source.resolve(),'-s',HERE/'import.csx','-o',output.resolve()],env,output.parent/'compile.log')
    after=bc.gmtt.snapshot(output)
    assert before['strings']==after['strings'][:len(before['strings'])]
    assert len(before['code'])==len(after['code'])
    changed_code=[]
    for a,b in zip(before['code'],after['code']):
        assert (a['index'],a['name'],a['parent'])==(b['index'],b['name'],b['parent'])
        if a!=b:
            assert a['name'] in PATHS,a['name']
            changed_code.append(a['name'])
    assert set(changed_code)==set(PATHS)
    additions={}
    for kind,values in before['resources'].items():
        updated=after['resources'][kind]
        if updated!=values:
            assert kind in ('Variables','Functions','CodeLocals') and updated[:len(values)]==values,kind
            additions[kind]=len(updated)-len(values)
    for key in before:
        if key not in ('strings','code','resources','source_size','source_sha256'):
            assert before[key]==after[key],key
    sites=bc.gmtt.site_map(after)
    # Recompiling an event can move its literal instruction indices. Match every
    # literal by ordinal within that same event, requiring the entire sequence
    # (including technical strings and duplicates) to be identical.
    remap={}
    for name in PATHS:
        old_sites=[(k,v) for k,v in before_sites.items() if v.get('code_name')==name]
        new_sites=[(k,v) for k,v in sites.items() if v.get('code_name')==name]
        assert [v['source'] for k,v in old_sites]==[v['source'] for k,v in new_sites],name
        for (old_id,a),(new_id,b) in zip(old_sites,new_sites):
            if old_id!=new_id:
                remap[old_id]=new_id
    assert all(sites[remap.get(k,k)]['source']==v for k,v in wanted.items()),'Canonical text changed'
    translated_remap={k:remap[k] for k in wanted if k in remap}
    bc.write(output.with_suffix('.site-remap.json'),{
        'input_sha256':expected,'output_sha256':after['source_sha256'],
        'method':'Identical ordered literal sequence within the same compiled event',
        'canonical_to_output':translated_remap})
    assert sites['GEN8:display_name']['source']=='Nightfall Princess | Translated by len'
    report={'input_sha256':expected,'output_sha256':after['source_sha256'],'bytes':output.stat().st_size,
            'changed_code':changed_code,'appended_resources':additions,'translated_sites_preserved':len(wanted),
            'all_other_code_preserved':True,'old_string_pool_preserved':True,
            'translated_sites_with_new_instruction_indices':translated_remap,
            'fonts_images_audio_save_identity_preserved':True,'bottom_padding':16,
            'wording_font_wrap_width_line_pitch_and_animation_preserved':True,'runtime_tested':False}
    bc.write(output.with_suffix('.narration-report.json'),report)
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('input',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--expected-input-sha256',default=BASE)
    args=parser.parse_args()
    build(args.input,args.output,args.expected_input_sha256)
