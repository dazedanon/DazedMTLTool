"""Run the final narration blocks and measure the corpus with the real engine."""
import json
import argparse
import os
from pathlib import Path
import shutil
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import build_catalog as bc
from build_followup import PATHS

parser=argparse.ArgumentParser()
parser.add_argument('--game',type=Path,default=bc.ROOT.parent,
                    help='Directory containing the licensed game executable and options.ini')
args=parser.parse_args()
assert (args.game/'Nightfall Princess.exe').is_file(), 'Pass --game with the game executable directory'

archive=HERE/'build-verified/data.win'
export=HERE/'verified-decompiled'
assert bc.read(export/'manifest.json')['source_sha256']==bc.gmtt.sha256(archive)
fixture=HERE/'canary-verified';fixture.mkdir(exist_ok=True)
catalog=bc.read(bc.ROOT/'build/catalog.en.json')
entries=[e for e in catalog['entries'] if e.get('translation_context',{}).get('field')=='scene.narration']
assert len(entries)==110
cases=[e['translation_context']['case_id'] for e in entries]
create='''window_set_caption("Nightfall Princess - narration QA");
window_set_size(1920,1080);
geo_text_time=50;
geo_text_alpha=1;
geo_text_y=0;
qa_path=0;
qa_case=1033;
camera_set_view_pos(view_camera[0],48,48);
camera_set_view_size(view_camera[0],1920,1080);
view_xport[0]=0;
view_yport[0]=0;
view_wport[0]=1920;
view_hport[0]=1080;
view_visible[0]=true;
view_enabled=false;
draw_set_font(font_1);
var qa_cases='''+json.dumps(cases)+''';
var qa_file=file_text_open_write("nfp_narration_qa_metrics.csv");
file_text_write_string(qa_file,"case,rows,height,line_height,max_width");
file_text_writeln(qa_file);
for(var qa_i=0;qa_i<array_length(qa_cases);qa_i++)
{
    var qa_text=scr_newline(scr_text_h(qa_cases[qa_i]),789);
    file_text_write_string(qa_file,string(qa_cases[qa_i])+","+string(string_count("\\n",qa_text)+1)+","+string(string_height_ext(qa_text,35,789))+","+string(string_height("A"))+","+string(string_width(qa_text)));
    file_text_writeln(qa_file);
}
file_text_close(qa_file);
'''
draw='''draw_clear(make_color_rgb(12,31,28));
draw_set_valign(fa_top);
geo_text=scr_text_h(qa_case);
switch(qa_path)
{
'''
for i,name in enumerate(PATHS):
    code=(export/'CodeEntries'/(name+'.gml')).read_text(encoding='utf-8')
    start=code.index('if (geo_text_time > 0)\n{')
    end=code.index('\n}',start)+2
    block=code[start:end]
    assert 'string_height_ext(tl_caption, 35, 789)' in block
    draw+=f'case {i}:\n'+block+'\n    break;\n'
draw+='''}
draw_set_font(font_2);
draw_set_colour(c_white);
draw_text(30,25,"Narration QA / renderer "+string(qa_path)+" / scene "+string(qa_case));
'''
step='''if(keyboard_check_pressed(vk_f8)) window_set_size(1366,768);
if(keyboard_check_pressed(vk_f6)) qa_path=(qa_path+1) mod 4;
if(keyboard_check_pressed(vk_f7)) qa_case=(qa_case==1033) ? 1024 : 1033;
view_enabled=(qa_path==3);
'''
changes=[]
for suffix,text in [('Create',create),('Step',step),('Draw',draw)]:
    name=f'gml_Object_obj_title_{suffix}_0'
    path=fixture/(name+'.gml');path.write_text(text,encoding='utf-8')
    changes.append({'name':name,'source':str(path)})
request=fixture/'request.json';bc.write(request,{'changes':changes})
env=os.environ.copy();env['NFP_TOOLTIP_CANARY']=str(request)
assert not (fixture/'data.win').exists()
bc.gmtt.run_utmt(['load',archive,'-s',bc.ROOT/'qa/tooltip_canary.csx','-o',fixture/'data.win'],env,fixture/'compile.log')
for name in ('Nightfall Princess.exe','options.ini'):
    shutil.copy2(args.game/name,fixture/name)
print(fixture/'data.win')
