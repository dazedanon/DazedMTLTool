"""Exercise the actual patched shop Draw event without entering gameplay."""
import json
import os
from pathlib import Path
import shutil
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import build_catalog as bc

archive=HERE/'build/data.win'
export=HERE/'decompiled'
assert bc.read(export/'manifest.json')['source_sha256']==bc.gmtt.sha256(archive)
draw=(export/'CodeEntries/gml_Object_obj_shop_Draw_0.gml').read_text(encoding='utf-8')
assert 'scr_text_quest(geo_mouse + (10 * (global.role_num - 2)))' in draw
fixture=HERE/'canary';fixture.mkdir(exist_ok=True)
create='''window_set_caption("Nightfall Princess - quest QA");
window_set_size(1920,1080);
global.role_num=2;
global.stage_clear=array_create(4);
global.quest_cd=array_create(4);
for(var qa_role=0;qa_role<4;qa_role++)
{
    global.stage_clear[qa_role]=array_create(10,0);
    global.quest_cd[qa_role]=array_create(10,0);
}
global.stage_clear[2][1]=1;
geo_left=3;
geo_mouse=11;
geo_page_max=0;
geo_sell=0;
geo_down_text="";
geo_right_e=array_create(10,0);
geo_right_sell=array_create(10,0);
geo_right_fit=array_create(10,0);
'''
fixture_draw='''draw_clear(make_color_rgb(12,31,28));
draw_set_alpha(1);
draw_set_valign(fa_top);
var qa_matrix=matrix_get(matrix_world);
matrix_set(matrix_world,matrix_build(-320,65,0,0,0,0,1,1,1));
'''+draw+'''
matrix_set(matrix_world,qa_matrix);
'''
step='if (keyboard_check_pressed(vk_f8)) window_set_size(1366,768);\n'
changes=[]
for suffix,text in [('Create',create),('Step',step),('Draw',fixture_draw)]:
    name=f'gml_Object_obj_title_{suffix}_0'
    path=fixture/(name+'.gml');path.write_text(text,encoding='utf-8')
    changes.append({'name':name,'source':str(path)})
request=fixture/'request.json';bc.write(request,{'changes':changes})
env=os.environ.copy();env['NFP_TOOLTIP_CANARY']=str(request)
assert not (fixture/'data.win').exists()
bc.gmtt.run_utmt(['load',archive,'-s',bc.ROOT/'qa/tooltip_canary.csx','-o',fixture/'data.win'],env,fixture/'compile.log')
for name in ('Nightfall Princess.exe','options.ini'):
    shutil.copy2(bc.ROOT.parent/name,fixture/name)
print(fixture/'data.win')
