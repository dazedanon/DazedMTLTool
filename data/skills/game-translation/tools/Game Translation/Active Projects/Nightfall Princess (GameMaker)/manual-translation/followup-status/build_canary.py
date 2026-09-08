"""Render the final stats Draw event and popup without entering gameplay."""
import json
import os
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import build_catalog as bc

archive=HERE/'build/data.win'
export=HERE/'final-decompiled'
receipt=json.loads((export/'manifest.json').read_text(encoding='utf-8'))
assert receipt['source_sha256']==bc.gmtt.sha256(archive)
code=export/'CodeEntries'
create=(code/'gml_Object_obj_state_Create_0.gml').read_text(encoding='utf-8')
assert create.startswith('obj_role.geo_stop = 1;\n')
create=create.removeprefix('obj_role.geo_stop = 1;\n')
draw=(code/'gml_Object_obj_state_Draw_0.gml').read_text(encoding='utf-8')
popup=(code/'gml_Object_obj_p_Draw_0.gml').read_text(encoding='utf-8')
fixture=HERE/'canary';fixture.mkdir(exist_ok=True)
title_create='''window_set_caption("Nightfall Princess - status QA");
window_set_size(1920,1080);
global.role_num=1;
global.h_num=array_create(4);
for(var qa_role=0;qa_role<4;qa_role++) global.h_num[qa_role]=array_create(8,0);
'''
title_draw='''draw_clear(make_color_rgb(28,23,19));
draw_set_alpha(1);
draw_set_valign(fa_top);
var qa_cases=[0,2,115];
var qa_matrix=matrix_get(matrix_world);
for(var qa_i=0;qa_i<3;qa_i++)
{
    global.role_num=qa_i+1;
    global.h_num[global.role_num][7]=qa_cases[qa_i];
    matrix_set(matrix_world,matrix_build(-951+590*qa_i,-222,0,0,0,0,1,1,1));
'''+create+draw+'''
}
matrix_set(matrix_world,qa_matrix);
geo_y=290;
geo_alpha=1;
'''+popup
title_step='''if (keyboard_check_pressed(vk_f8)) window_set_size(1366,768);
'''
changes=[]
for suffix,text in [('Create',title_create),('Step',title_step),('Draw',title_draw)]:
    name=f'gml_Object_obj_title_{suffix}_0'
    path=fixture/(name+'.gml');path.write_text(text,encoding='utf-8')
    changes.append({'name':name,'source':str(path)})
request=fixture/'request.json';request.write_text(json.dumps({'changes':changes}),encoding='utf-8')
env=os.environ.copy();env['NFP_TOOLTIP_CANARY']=str(request)
assert not (fixture/'data.win').exists()
bc.gmtt.run_utmt(['load',archive,'-s',bc.ROOT/'qa/tooltip_canary.csx','-o',fixture/'data.win'],env,fixture/'compile.log')
print(fixture/'data.win')
