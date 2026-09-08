"""Validate wrapped captions against actual room/view bounds and engine metrics."""
import csv
import re
import build_catalog as bc

HERE=bc.ROOT/'followup-narration'

def audit(measurements):
    font=next(f for f in bc.read(bc.PROJECT/'source/snapshot.json')['fonts'] if f['name']=='font_1')
    report=bc.read(HERE/'build-verified/data.narration-report.json')
    export=HERE/'verified-decompiled'
    assert bc.read(export/'manifest.json')['source_sha256']==report['output_sha256']
    metrics={int(r['case']):{k:float(v) for k,v in r.items()} for r in csv.DictReader((HERE/'engine-metrics.csv').open())}
    entries={e['id']:e for e in bc.read(bc.ROOT/'build/catalog.en.json')['entries']}
    captions=[r for r in measurements if r['context']=='scene']
    assert len(captions)==len(metrics)==110
    rooms=bc.read(HERE/'room-geometry.json')
    # All rooms without enabled views use their 1080-pixel room canvas. The
    # three battle rooms use a 1080-pixel view starting at world y=48.
    for room in rooms:
        active='EnableViews' in room['dimensions']['Flags']
        if active:
            enabled=[v for v in room['views'] if v['Enabled']=='True']
            assert len(enabled)==1
            assert (enabled[0]['ViewY'],enabled[0]['ViewHeight'])==('48','1080')
        else:
            assert room['dimensions']['Height']=='1080'
    values=[]
    for name,base_y,camera_y in [('hall',940,0),('quest',940,0),('gallery',940,0),('ui',988,48)]:
        code=(export/f'CodeEntries/gml_Object_obj_{name}_Draw_0.gml').read_text(encoding='utf-8')
        assert 'var tl_caption = scr_newline(geo_text, 789);' in code
        assert 'var tl_caption_bottom = room_height - 16;' in code and 'if (view_enabled)' in code
        assert '(camera_get_view_y(view_camera[0]) + camera_get_view_height(view_camera[0])) - 16;' in code
        assert f'min({base_y}, tl_caption_bottom - string_height_ext(tl_caption, 35, 789))' in code
        assert 'tl_caption_y - geo_text_y, tl_caption, 35, 789)' in code
        step=(bc.PROJECT/f'source/gml/gml_Object_obj_{name}_Step_0.gml').read_text(encoding='utf-8')
        assert 'geo_text_y += geo_text_speed;' in step and 'geo_text_speed -= 0.7;' in step
        assert re.search(r'if \(geo_text_y < 0 && geo_text_stop == 0\)\s*\{\s*geo_text_y = 0;',step)
        bottom=camera_y+1080-16
        for row in captions:
            case=entries[row['id']]['translation_context']['case_id']
            measured=metrics[case]
            height=font['line_height']+(row['rows']-1)*35
            widths=[bc.gmtt.font_measure(s,font)['line_widths'][0] for s in row['lines']]
            assert (measured['rows'],measured['height'],measured['line_height'])==(row['rows'],height,font['line_height'])
            assert measured['max_width']==max(widths)<=789
            top=min(base_y,bottom-height)
            assert top+height<=bottom and top>=camera_y
            if base_y+height<=bottom: assert top==base_y
            values.append({'id':row['id'],'renderer':name,'rows':row['rows'],'height':height,
                           'previous_screen_bottom':base_y-camera_y+height,
                           'new_screen_top':top-camera_y,'new_screen_bottom':top-camera_y+height,
                           'moved_up':base_y-top})
    known=[r for r in values if r['id']=='CODE:82:947']
    assert len(known)==4 and all(r['previous_screen_bottom']==1094 and r['new_screen_bottom']==1064 for r in known)
    result={'caption_entries':110,'renderer_paths':4,'measured_combinations':len(values),
            'engine_font_metrics_matched':True,'camera_geometry_checked':True,
            'previously_overflowing_combinations':sum(r['previous_screen_bottom']>1080 for r in values),
            'shifted_combinations':sum(r['moved_up']>0 for r in values),
            'minimum_line_box_bottom_margin':min(1080-r['new_screen_bottom'] for r in values),
            'remaining_overflows':0,'rows':values}
    bc.write(bc.ROOT/'build/narration-layout-audit.json',result)
    return result
