"""Targeted scene fixtures for transient warnings and the concluding image.

The completed normal playthrough is in image_visible.json. This separate check
enters scene starts directly, then uses only the ordinary choices/page control.
"""
import hashlib,json,time
from pathlib import Path
from cdp_client import CDPClient
ROOT=Path(__file__).resolve().parents[1]
report={'archive_sha256':hashlib.sha256((ROOT/'test_game/resources/app.asar').read_bytes()).hexdigest(),
        'fixture_entry':'Directly enter scene4 and scene9 starts; then ordinary controls.', 'screenshots':[]}
with CDPClient() as c:
 c.call('Runtime.enable')
 def state():return c.evaluate("""(()=>{const k=TYRANO.kag;return {scenario:k.stat.current_scenario,index:k.ftag.current_order_index,wait:k.stat.is_wait,
  controls:[...document.querySelectorAll('[data-event-tag]')].filter(e=>$(e).is(':visible')).map(e=>JSON.parse(e.getAttribute('data-event-pm')||'{}')).filter(x=>!x.role),
  images:[...document.querySelectorAll('img')].filter(e=>$(e).is(':visible')&&e.complete&&e.naturalWidth).map(e=>({src:e.src,w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height}))}})()""")
 def click(target):
  c.evaluate("$('[data-event-tag]').filter((i,e)=>$(e).is(':visible')&&JSON.parse(e.getAttribute('data-event-pm')||'{}').target==="+json.dumps(target)+").trigger('click');true")
 def shot(name,asset,s):
  path=ROOT/'reports'/('qa_images_targeted_'+name+'.png');c.screenshot(path)
  report['screenshots'].append({'file':path.relative_to(ROOT).as_posix(),'assets':[asset],'state':s})
 def reset():
  c.evaluate('TYRANO.kag.menu.loadGame(0);true')
  end=time.monotonic()+10
  while time.monotonic()<end:
   s=state()
   if s['scenario']=='scene1.ks' and not s['wait']:
    time.sleep(.25);return
   time.sleep(.05)
  raise AssertionError('Legacy scene fixture did not load')
 reset()
 c.evaluate("TYRANO.kag.ftag.startTag('jump',{storage:'scene4_insert.ks',target:'*start'});true")
 end=time.monotonic()+10
 while time.monotonic()<end:
  if any('ev_insert_explain.jpg'in x['src']for x in state()['images']):break
  time.sleep(.05)
 else:raise AssertionError('Insertion fixture did not open')
 caught=set();end=time.monotonic()+25
 while time.monotonic()<end:
  s=state()
  for name,file in [('wimp','ui_icon_hetare.png'),('danger','ui_icon_danger.png')]:
   if name not in caught and any(file in x['src']for x in s['images']):
    shot(name,'data/fgimage/default/'+file,s);caught.add(name)
  if len(caught)==2:break
  if not s['wait']:
   target=next((x.get('target')for x in s['controls']if x.get('target')in('*face1_safe_stop','*face2_safe_go','*face3_mid_go')),None)
   if target:click(target)
   elif not s['controls']:c.evaluate('TYRANO.kag.key_mouse.next()')
  time.sleep(.025)
 assert caught=={'wimp','danger'},(caught,state())
 # Let the warning's timer finish before replacing the scenario fixture.
 end=time.monotonic()+3
 while state()['wait'] and time.monotonic()<end:time.sleep(.05)
 reset()
 c.evaluate("TYRANO.kag.ftag.startTag('jump',{storage:'scene9_baby.ks',target:'*start'});true")
 found=False;end=time.monotonic()+25
 while time.monotonic()<end:
  s=state()
  if not s['wait'] and any('ev_baby8.jpg'in x['src']for x in s['images']):
   c.evaluate("$('[data-event-tag]').filter((i,e)=>$(e).is(':visible')&&JSON.parse(e.getAttribute('data-event-pm')||'{}').role==='window').trigger('click');true")
   time.sleep(.25);shot('conclusion','data/fgimage/default/ev_baby8.jpg',state());found=True;break
  if not s['wait']:c.evaluate('TYRANO.kag.key_mouse.next()')
  time.sleep(.12)
 assert found,state()
 report['exceptions']=[e for e in c.events if e['method']=='Runtime.exceptionThrown']
 assert not report['exceptions']
report['passed']=True
(ROOT/'reports/image_targeted.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps({'passed':True,'screenshots':len(report['screenshots'])}))
