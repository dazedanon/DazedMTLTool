"""Normal-control route and screenshot coverage for the isolated image patch."""
import argparse,hashlib,json,time
from pathlib import Path
from cdp_client import CDPClient
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=50);p.add_argument('--stop-at',default='');a=p.parse_args()
manifest=json.loads((ROOT/'images/manifest.json').read_text(encoding='utf8'))
paths={x['path']for x in manifest['assets']}
rep=ROOT/'reports/image_visible.json'
archive=ROOT/'test_game/resources/app.asar'
digest=hashlib.sha256(archive.read_bytes()).hexdigest()
report=json.loads(rep.read_text(encoding='utf8'))if rep.exists()else {'archive_sha256':digest,'observations':[],'screenshots':[],'exceptions':[]}
assert report['archive_sha256']==digest
observed={p for r in report['screenshots'] for p in r['assets']}
state_js=r"""(()=>{const k=TYRANO.kag;
 const controls=[...document.querySelectorAll('[data-event-tag]')].map((e,i)=>({e,i,tag:e.getAttribute('data-event-tag'),pm:JSON.parse(e.getAttribute('data-event-pm')||'{}')})).filter(x=>!x.pm.role&&$(x.e).is(':visible')&&getComputedStyle(x.e).pointerEvents!=='none');
 const imgs=[...document.querySelectorAll('img')].filter(e=>$(e).is(':visible')&&e.complete&&e.naturalWidth&&getComputedStyle(e).opacity!=='0').map(e=>({src:e.src,w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height}));
 for(const e of document.querySelectorAll('.layer,.layer_camera,.base_fore')){const s=getComputedStyle(e);if($(e).is(':visible')&&s.backgroundImage!=='none')imgs.push({src:s.backgroundImage,w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height});}
 return {scenario:k.stat.current_scenario,index:k.ftag.current_order_index,adding:k.stat.is_adding_text,wait:k.stat.is_wait,strong:k.stat.is_strong_stop,variables:k.stat.f,images:imgs,controls:controls.map(({i,tag,pm})=>({i,tag,pm}))};})()"""
def seen(s):return {p for p in paths for x in s['images'] if p in x['src'] and x['w']>0 and x['h']>0}
with CDPClient()as c:
 c.call('Runtime.enable');end=time.monotonic()+min(a.seconds,55);previous=None
 while time.monotonic()<end:
  s=c.evaluate(state_js);key=(s['scenario'],s['index'])
  if key!=previous:report['observations'].append(s);previous=key
  current=seen(s)
  if current-observed and not s['wait']:
   time.sleep(.25);s=c.evaluate(state_js);current=seen(s)
   # Never capture the excluded listing image, even if a translated control is visible.
   excluded=any('ev_Hdouga.jpg'in x['src']for x in s['images'])
   if current-observed and not excluded:
    shot=ROOT/'reports'/f'qa_images_{len(report["screenshots"]):02}_{s["scenario"].removesuffix(".ks")}.png'
    c.screenshot(shot)
    report['screenshots'].append({'file':shot.relative_to(ROOT).as_posix(),'scenario':s['scenario'],'index':s['index'],'assets':sorted(current),'geometry':s['images']})
    observed|=current
  if a.stop_at and s['scenario']==a.stop_at:break
  if s['scenario']=='title_screen.ks' and any(x['scenario']!='title_screen.ks'for x in report['observations']):break
  opts=s['controls'];selected=None
  if opts:
   if s['scenario']=='title_screen.ks':selected=next((x for x in opts if x['pm'].get('target')=='*start'),None)
   elif s['scenario']=='scene2_undress.ks':selected=next((x for x in opts if x['pm'].get('target')=='*hit'),None)
   elif s['scenario']=='scene4_insert.ks':
    selected=next((x for x in opts if '_safe_go'in x['pm'].get('target','')),None)
    if selected is None:selected=next((x for x in opts if x['pm'].get('target','').endswith('_stop')),None)
   elif s['scenario']=='scene5_piston.ks':
    goal='*start'if s['variables'].get('piston',0)>=12 else '*piston_deep_fast'
    selected=next((x for x in opts if x['pm'].get('target')==goal),None)
   elif s['scenario']=='scene6_sanran.ks':
    selected=next((x for x in opts if x['pm'].get('target')in('*umu_fast','*25kara','*39kara','*48kara')),None)
    if selected is None:selected=next((x for x in opts if x['pm'].get('target')=='*umu'),None)
    if selected is None:selected=next((x for x in opts if x['tag']in('clickable','glink')),None)
   elif s['scenario']=='scene8_syussan.ks':
    selected=next((x for x in opts if x['pm'].get('storage')=='scene9_baby.ks'),None)
    if selected is None:selected=next((x for x in opts if x['pm'].get('target')in('*Hdouga','*okini')),None)
   else:selected=next((x for x in opts if x['tag']in('clickable','glink')),None)
  if selected:c.evaluate(f"$([...document.querySelectorAll('[data-event-tag]')][{selected['i']}]).trigger('click');true")
  elif not s['wait']:c.evaluate('TYRANO.kag.key_mouse.next()')
  time.sleep(.12)
 report['exceptions'] += [e for e in c.events if e['method']=='Runtime.exceptionThrown']
 report['last_state']=c.evaluate(state_js)
rep.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print(json.dumps({'scenario':report['last_state']['scenario'],'index':report['last_state']['index'],'visible_images':len(observed),'screenshots':len(report['screenshots']),'exceptions':len(report['exceptions'])}))
