"""Open actual theme menus in the isolated game and preserve screenshot evidence."""
import hashlib,json,time
from pathlib import Path
from cdp_client import CDPClient
ROOT=Path(__file__).resolve().parents[1]
report={'archive_sha256':hashlib.sha256((ROOT/'test_game/resources/app.asar').read_bytes()).hexdigest(),'checks':{},'screenshots':[]}
with CDPClient() as c:
 c.call('Runtime.enable')
 def wait(expr,seconds=12):
  end=time.monotonic()+seconds
  while time.monotonic()<end:
   if c.evaluate(expr):return
   time.sleep(.08)
  raise AssertionError(expr)
 def shot(name):
  time.sleep(.35)
  assert c.evaluate("[...document.querySelectorAll('img')].filter(e=>$(e).is(':visible')).every(e=>e.complete&&e.naturalWidth>0)")
  path=ROOT/'reports'/('qa_images_menu_'+name+'.png');c.screenshot(path)
  report['screenshots'].append(path.relative_to(ROOT).as_posix())
 def close():
  c.evaluate("$('.layer_menu .menu_close:visible').trigger('click');true")
  wait("!$('.layer_menu').is(':visible')")
 for name,method in [('save','displaySave'),('load','displayLoad')]:
  c.evaluate('TYRANO.kag.menu.'+method+'();true')
  wait("$('.save_list:visible').length>0")
  shot(name)
  titles=c.evaluate("$('.save_list_item_text:visible').map((i,e)=>$(e).text()).get()")
  assert titles and all(not any('\u3040'<=x<='\u9fff' for x in s)for s in titles),titles
  report['checks'][name+'_english_captions']=titles
  close()
 c.evaluate("$('[data-event-tag]').filter((i,e)=>JSON.parse(e.getAttribute('data-event-pm')||'{}').role==='backlog').trigger('click');true")
 wait("$('.layer_menu:visible').length>0")
 shot('backlog');report['checks']['backlog_opened']=True;close()
 c.evaluate('TYRANO.kag.menu.showMenu();true')
 wait("$('.menu_save:visible').length>0")
 shot('main')
 before=c.evaluate("$('.menu_save img').attr('src')")
 c.evaluate("$('.menu_save img').trigger('mouseenter');true")
 hover=c.evaluate("$('.menu_save img').attr('src')")
 assert hover==before.replace('.png','2.png'),(before,hover)
 c.evaluate("$('.menu_save img').trigger('mouseleave');true")
 assert c.evaluate("$('.menu_save img').attr('src')")==before
 report['checks']['menu_hover_restores_image']=True
 c.evaluate("$('.menu_config a').trigger('click');true")
 wait("TYRANO.kag.stat.current_scenario.includes('config.ks')&&TYRANO.kag.stat.is_strong_stop")
 shot('configuration')
 report['checks']['configuration_sample']=c.evaluate('gMessageTester.sampleTexts')
 c.evaluate("$('[data-event-tag]').filter((i,e)=>JSON.parse(e.getAttribute('data-event-pm')||'{}').target==='*backtitle').trigger('click');true")
 wait("TYRANO.kag.stat.current_scenario==='scene1.ks'")
 report['checks']['configuration_returns_to_game']=True
 report['exceptions']=[e for e in c.events if e['method']=='Runtime.exceptionThrown']
 assert not report['exceptions']
report['passed']=True
(ROOT/'reports/image_menus.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps({'passed':True,'screenshots':len(report['screenshots'])}))
