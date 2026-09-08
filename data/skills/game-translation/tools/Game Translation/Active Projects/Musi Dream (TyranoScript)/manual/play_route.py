"""Exercise ordinary clickable controls in the isolated game; never jump scenarios."""
import argparse
import json
import time
from pathlib import Path
from cdp_client import CDPClient

p=argparse.ArgumentParser()
p.add_argument('--seconds',type=int,default=50)
p.add_argument('--piston',type=int,default=12)
p.add_argument('--stop-at',default='')
p.add_argument('--route',default='main')
a=p.parse_args()
root=Path(__file__).resolve().parents[1]
report=root/'reports'/('play_'+a.route+'.jsonl')
state_js="""(()=>{const k=TYRANO.kag;
const controls=[...document.querySelectorAll('[data-event-tag]')].map((e,i)=>({e,i,tag:e.getAttribute('data-event-tag'),pm:JSON.parse(e.getAttribute('data-event-pm')||'{}')})).filter(x=>!x.pm.role&&$(x.e).is(':visible')&&getComputedStyle(x.e).pointerEvents!=='none');
return {scenario:k.stat.current_scenario,index:k.ftag.current_order_index,text:[...document.querySelectorAll('.message_inner')].filter(x=>$(x).is(':visible')).map(x=>x.innerText).join('|'),adding:k.stat.is_adding_text,wait:k.stat.is_wait,strong:k.stat.is_strong_stop,variables:k.stat.f,controls:controls.map(({i,tag,pm})=>({i,tag,pm}))};})()"""
with CDPClient() as c, report.open('a',encoding='utf-8') as log:
    c.call('Runtime.enable')
    deadline=time.monotonic()+min(a.seconds,55)
    previous=None
    while time.monotonic()<deadline:
        s=c.evaluate(state_js)
        key=(s['scenario'],s['index'])
        if key!=previous:
            log.write(json.dumps(s,ensure_ascii=False)+'\n');log.flush();previous=key
        if a.stop_at and s['scenario']==a.stop_at:
            print(json.dumps({'stopped':s},ensure_ascii=True));break
        options=s['controls']
        if any(x['pm'].get('storage')=='title_screen.ks' for x in options) and s['scenario']!='title_screen.ks':
            print(json.dumps({'ending':s},ensure_ascii=True));break
        selected=None
        if options:
            if s['scenario']=='scene5_piston.ks':
                goal='*start' if s['variables'].get('piston',0)>=a.piston else '*piston_deep_fast'
                selected=next((x for x in options if x['pm'].get('target')==goal),None)
            elif s['scenario']=='scene2_undress.ks':
                selected=next((x for x in options if x['pm'].get('target')=='*hit'),None)
            elif s['scenario']=='scene4_insert.ks':
                selected=next((x for x in options if '_safe_go' in x['pm'].get('target','')),None)
                if selected is None:
                    selected=next((x for x in options if x['pm'].get('target','').endswith('_stop')),None)
            elif s['scenario']=='scene6_sanran.ks':
                selected=next((x for x in options if x['pm'].get('target') in ('*umu','*25kara','*39kara','*48kara')),None)
                if selected is None:
                    selected=next((x for x in options if x['tag'] in ('clickable','glink')),None)
            elif s['scenario']=='scene8_syussan.ks':
                selected=next((x for x in options if x['pm'].get('storage')=='scene9_baby.ks'),None)
                if selected is None:
                    selected=next((x for x in options if x['pm'].get('target') in ('*Hdouga','*okini')),None)
            else:
                selected=next((x for x in options if x['tag'] in ('clickable','glink')),None)
        if selected:
            c.evaluate(f"$([...document.querySelectorAll('[data-event-tag]')][{selected['i']}]).trigger('click');true")
        elif not s['wait']:
            c.evaluate('TYRANO.kag.key_mouse.next()')
        time.sleep(.13)
    else:
        print(json.dumps({'paused':s,'events':[e for e in c.events if e['method']=='Runtime.exceptionThrown']},ensure_ascii=True))
