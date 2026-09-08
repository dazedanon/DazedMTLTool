"""Exercise the shipped tooltip draw block in-engine without entering gameplay."""
import json
import argparse
import os
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT))
from build_catalog import gmtt
parser=argparse.ArgumentParser()
parser.add_argument('archive',type=Path,nargs='?',default=ROOT/'release/data.win')
args=parser.parse_args()

decompiled=HERE/'tooltip-decompiled/CodeEntries/gml_Object_obj_talent_Draw_0.gml'
source=decompiled.read_text(encoding='utf-8')
start=source.index('if (geo_now != -1 && geo_mouse_x > 0 && geo_mouse_y > 0')
end=source.rindex('draw_set_alpha(1);')
block=source[start:end]
assert 'draw_text_transformed(' in block and 'tmp_title_scale' in block
canary=HERE/'tooltip-canary';canary.mkdir(exist_ok=True)
create='window_set_caption("Nightfall Princess - tooltip QA");\nwindow_set_size(1920, 1080);\nglobal.role_num = 1;\nglobal.role_point = 1;\nglobal.talent_cover = 0;\n'
draw='''draw_clear(make_color_rgb(24, 20, 17));
draw_set_alpha(1);
draw_set_color(c_white);
draw_set_halign(fa_left);
draw_set_valign(fa_top);
var qa_cases = [5, 6, 24, 68, 79, 7];
for (var qa_i = 0; qa_i < 6; qa_i += 1)
{
    x = 350 + ((qa_i mod 3) * 390);
    y = 220 + (floor(qa_i / 3) * 270);
    geo_now = 1;
    geo_mouse_x = 1;
    geo_mouse_y = 1;
    geo_talent[1][1] = 11;
    if (qa_i == 5) geo_talent[1][1] = 7;
    geo_skill[1] = qa_cases[qa_i];
'''+block+'\n}\n'
changes=[]
for suffix,code in [('Create',create),('Step',''),('Draw',draw)]:
    name=f'gml_Object_obj_title_{suffix}_0';path=canary/(name+'.gml');path.write_text(code,encoding='utf-8')
    changes.append({'name':name,'source':str(path)})
req=canary/'request.json';req.write_text(json.dumps({'changes':changes}),encoding='utf-8')
env=os.environ.copy();env['NFP_TOOLTIP_CANARY']=str(req)
gmtt.run_utmt(['load',args.archive.resolve(),'-s',HERE/'tooltip_canary.csx','-o',canary/'data.win'],env,canary/'compile.log')
print(str(canary/'data.win'))
