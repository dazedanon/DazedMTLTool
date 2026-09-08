"""Build translated text plus a separately audited, additive save-display plugin."""
from pathlib import Path
import sys,json
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
sys.path.insert(0,str(BASE));import tl
output=Path(sys.argv[1]).resolve()
report=tl.build(output,phase=2)
units=tl.read_json(tl.STORE)['units'];readmap={}
for u in units:
    if u['kind']!='dialogue':continue
    for site in u['sites']:
        if site['mode']!='run':continue
        p=site['path'];rel=site['file']
        if rel=='data/CommonEvents.json':mapid,event,page=1,p[0],0
        elif rel=='data/Troops.json':mapid,event,page=0,p[0],p[2]
        else:mapid,event,page=int(Path(rel).stem[3:])+1,p[1],p[3]
        key='/'.join(map(str,[mapid,event,page,site['start']-1]))
        value=''.join(site['original'])
        assert key not in readmap or readmap[key]==value
        readmap[key]=value
old=tl.read_json(tl.SOURCE/'data/Actors.json');new=tl.read_json(output/'data/Actors.json')
actors=[[i,a['name'],new[i]['name']] for i,a in enumerate(old) if a and a['name']!=new[i]['name']]
values=[[125,u['source'],tl.targets_for({'units':[u]})[u['id']]] for u in units if u['kind']=='status_value']
script=(HERE/'english_runtime.js').read_text(encoding='utf-8')
for token,value in [('__ORIGINAL_READ_TEXT__',readmap),('__ACTOR_NAMES__',actors),('__DISPLAY_VALUES__',values)]:
    script=script.replace(token,json.dumps(value,ensure_ascii=True,separators=(',',':')))
plugin='js/plugins/TropicalChaseEnglish.js'
(output/plugin).write_text(script,encoding='utf-8')
registration='\n$plugins.push({name:"TropicalChaseEnglish",status:true,description:"English save display compatibility",parameters:{}});\n'
p=output/'js/plugins.js';p.write_bytes(p.read_bytes()+registration.encode())
tl.js_parse([{'name':plugin,'source':script},{'name':'js/plugins.js','source':tl.read_text(p)}])
report['runtime_extension']={'file':plugin,'actors':actors,'display_values':values,'read_history_keys':len(readmap),
    'changes':'One appended plugin registration outside the original array; exact-value cached display refresh; original read-history keys; results-only panel expansion and text containment. No event command or gameplay changes.',
    'source_sha256':tl.sha((HERE/'english_runtime.js').read_bytes()),'builder_sha256':tl.sha(Path(__file__).read_bytes())}
for rel in [plugin,'js/plugins.js']:
    if rel not in report['changed_files']:report['changed_files'].append(rel)
    report['output_hashes'][rel]=tl.sha((output/rel).read_bytes())
tl.write_json(output/'BUILD_REPORT.json',report)
print(json.dumps({'build':output.name,'translated':report['translated_units'],'changed_files':len(report['changed_files']),'read_history_keys':len(readmap),'source_corrections':len(report['source_corrections'])}))
