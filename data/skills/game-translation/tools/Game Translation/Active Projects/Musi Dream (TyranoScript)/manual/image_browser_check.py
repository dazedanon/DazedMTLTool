"""Exercise the translated browser and removed-page branch using their controls."""
import hashlib,json,time
from pathlib import Path
from cdp_client import CDPClient
ROOT=Path(__file__).resolve().parents[1]
report={'archive_sha256':hashlib.sha256((ROOT/'test_game/resources/app.asar').read_bytes()).hexdigest(),'screenshots':[],'checks':{}}
with CDPClient() as c:
 c.call('Runtime.enable')
 assert c.evaluate("TYRANO.kag.stat.current_scenario==='scene8_syussan.ks'")
 def wait(expr,seconds=10):
  end=time.monotonic()+seconds
  while time.monotonic()<end:
   if c.evaluate(expr):return
   time.sleep(.05)
  raise AssertionError(expr)
 def bg(name):return "[...document.querySelectorAll('.layer,.base_fore')].some(e=>$(e).is(':visible')&&getComputedStyle(e).backgroundImage.includes("+json.dumps(name)+"))"
 def click(target):
  ok=c.evaluate("(()=>{const e=[...document.querySelectorAll('[data-event-tag]')].find(e=>$(e).is(':visible')&&JSON.parse(e.getAttribute('data-event-pm')||'{}').target==="+json.dumps(target)+");if(!e)return false;$(e).trigger('click');return true})()")
  assert ok,target
 def shot(name,assets):
  assert not c.evaluate(bg('ev_Hdouga.jpg'))
  time.sleep(.25)
  path=ROOT/'reports'/('qa_images_browser_'+name+'.png');c.screenshot(path)
  report['screenshots'].append({'file':path.relative_to(ROOT).as_posix(),'assets':assets})
 c.evaluate('TYRANO.kag.key_mouse.next()')
 wait(bg('ev_Ytube.jpg'))
 shot('ytube',['data/bgimage/ev_Ytube.jpg'])
 click('*sakuzyo');wait(bg('ev_sakuzyo.jpg'))
 shot('removed',['data/bgimage/ev_sakuzyo.jpg'])
 report['checks']['removed_tile_opens_translated_page']=True
 click('*ytube');wait(bg('ev_Ytube.jpg'))
 report['checks']['back_returns_to_browser']=True
 click('*okini')
 wait("[...document.querySelectorAll('[data-event-tag]')].some(e=>$(e).is(':visible')&&JSON.parse(e.getAttribute('data-event-pm')||'{}').target==='*Hdouga')")
 shot('favorites',['data/bgimage/ev_Ytube.jpg'])
 report['checks']['favorites_overlay_opens']=True
 report['exceptions']=[e for e in c.events if e['method']=='Runtime.exceptionThrown']
 assert not report['exceptions']
report['passed']=True
(ROOT/'reports/image_browser.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps({'passed':True,'checks':report['checks']}))
