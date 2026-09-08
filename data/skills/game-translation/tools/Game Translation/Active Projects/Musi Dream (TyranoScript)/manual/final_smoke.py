"""Final isolated runtime probes, pinned to the actually installed archive."""
import hashlib
import json
import time
from pathlib import Path
from cdp_client import CDPClient

root=Path(__file__).resolve().parents[1]
archive=root/'test_game/resources/app.asar'
with archive.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
report={'archive_sha256':digest,'checks':{}}
def pause(c, predicate, timeout=12):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if c.evaluate(predicate):return
        time.sleep(.12)
    raise AssertionError('Timed out: '+predicate)

with CDPClient() as c:
    c.call('Runtime.enable')
    c.evaluate('TYRANO.kag.menu.loadGame(0);true')
    pause(c,"TYRANO.kag.stat.current_scenario==='scene1.ks'&&!TYRANO.kag.stat.is_wait")
    state=c.evaluate("({index:TYRANO.kag.ftag.current_order_index,speaker:TYRANO.kag.stat.current_speaker,text:$('.message_inner:visible').text()})")
    assert state['speaker']=='Small-Time Ytuber Himarii',state
    assert state['text']=="Yaaay! It's finally over!",state
    report['checks']['legacy_save']=state
    c.screenshot(root/'reports/qa_final_legacy_save.png')
    c.evaluate('TYRANO.kag.key_mouse.next()')
    pause(c,"!TYRANO.kag.stat.is_adding_text&&TYRANO.kag.stat.current_message_str.includes('Kiwi')")
    saved=c.evaluate("new Promise(resolve=>{const k=TYRANO.kag;k.menu.snap=null;k.menu.snapSave(k.stat.current_save_str,()=>k.menu.doSave(2,()=>resolve({title:k.menu.getSaveData().data[2].title,index:k.ftag.current_order_index,f:k.stat.f})), 'false')})")
    assert saved['title'].startswith('Small-Time Ytuber Himarii:'),saved
    assert not any('\u3040'<=x<='\u9fff' for x in saved['title']),saved
    c.evaluate('TYRANO.kag.key_mouse.next()')
    c.evaluate('TYRANO.kag.menu.loadGame(2);true')
    pause(c,"!TYRANO.kag.stat.is_wait&&$('.message_inner:visible').text().includes('Kiwi')")
    loaded=c.evaluate("({title:TYRANO.kag.menu.getSaveData().data[2].title,index:TYRANO.kag.ftag.current_order_index,f:TYRANO.kag.stat.f})")
    assert saved==loaded,(saved,loaded)
    report['checks']['english_save_reload']=loaded
    c.screenshot(root/'reports/qa_final_english_reload.png')
    sample=c.evaluate('gMessageTester.sampleTexts')
    assert sample==['I am a cat. As yet, I have no name.','I have no idea where I was born. All I remember is mewing in some dark, damp place.'],sample
    report['checks']['sample_spaces']=sample
    captions=c.evaluate('TYRANO.kag.menu.getSaveData().data.map(x=>x.title)')
    assert all(not any('\u3040'<=x<='\u9fff' for x in title) for title in captions),captions
    report['checks']['save_menu_captions']=captions
    report['runtime_exceptions']=[e for e in c.events if e['method']=='Runtime.exceptionThrown']
    assert not report['runtime_exceptions']
report['passed']=True
(root/'reports/final_smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=True,indent=2))
