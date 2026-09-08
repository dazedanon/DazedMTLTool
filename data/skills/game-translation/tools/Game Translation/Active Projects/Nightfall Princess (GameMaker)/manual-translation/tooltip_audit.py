"""Regression for the player-reported skill tooltip title overflow."""
import json
import re
import build_catalog as bc

def main():
    catalog = bc.read(bc.ROOT/'build/catalog.en.json')
    snapshot = bc.read(bc.PROJECT/'source/snapshot.json')
    font = next(f for f in snapshot['fonts'] if f['name']=='font_b1')
    layout = (bc.ROOT/'layout/gml_Object_obj_talent_Draw_0.gml').read_text(encoding='utf-8')
    right = int(re.search(r'sprite_get_width\(spr_talent_bg_2\) - 70 - (\d+)',layout)[1])
    assert 'min(1, tmp_title_width / max(1, string_width(tmp_title)))' in layout
    assert 'draw_text_transformed(tmp_x + 70, tmp_title_y, tmp_title, tmp_title_scale, tmp_title_scale, 0)' in layout
    assets=bc.read(bc.ROOT/'images/source/manifest.json')
    plate=next(r for r in assets if r['sprite']=='spr_talent_bg_2')['sprite_size']
    entries=[e for e in catalog['entries'] if e.get('translation_context',{}).get('field') in ('name.skill','name.stat')]
    # CD is an original ASCII stat name, outside the Japanese string catalog.
    source=(bc.PROJECT/'source/gml/gml_GlobalScript_scr_name_talent.gml').read_text(encoding='utf-8')
    assert re.search(r'case 8:\s*tmp_str = "CD";',source)
    entries.append({'id':'ASCII:stat:8','source':'CD','translation':'CD','translation_context':{'field':'name.stat'}})
    rows=[]
    for entry in entries:
        skill=entry['translation_context']['field']=='name.skill'
        left=70 if skill else 66
        width=bc.gmtt.font_measure(entry['translation'],font)['line_widths'][0]
        source_width=bc.gmtt.font_measure(entry['source'],font)['line_widths'][0]
        budget=plate[0]-left-right
        scale=min(1,budget/max(1,width)) if skill else 1
        assert source_width<=budget, ('Source does not fit; check geometry',entry['id'])
        assert width*scale<=budget+1e-6,entry['id']
        assert scale>=0.85, ('Name needs an editorial/layout review',entry['id'])
        rows.append({'id':entry['id'],'name':entry['translation'],'font':'font_b1','source_width':source_width,
                     'unscaled_width':width,'available_width':budget,'scale':scale,
                     'right_edge':left+width*scale,'right_padding':plate[0]-left-width*scale,
                     'case_id':entry.get('translation_context',{}).get('case_id',8)})
    assert len(rows)==89
    changed=[r for r in rows if r['scale']<1]
    assert any(r['name']=='Weapon Enchantment' and r['unscaled_width']>r['available_width'] for r in changed)
    report={'checked_titles':len(rows),'previous_overflows':len(changed),'remaining_overflows':0,
            'smallest_scale':min(r['scale'] for r in rows),'plate_size':plate,'titles':rows}
    bc.write(bc.ROOT/'build/tooltip-title-audit.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='titles'}))
    print(json.dumps(changed,indent=2))

if __name__=='__main__':main()
