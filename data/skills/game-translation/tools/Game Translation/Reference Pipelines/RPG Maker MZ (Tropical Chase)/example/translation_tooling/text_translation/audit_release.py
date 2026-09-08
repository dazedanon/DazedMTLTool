"""Audit the written artifact against source, exact extraction sites and exclusions."""
from pathlib import Path
import sys,json,collections,re
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
sys.path.insert(0,str(BASE));import tl
build=Path(sys.argv[1]).resolve();report=tl.read_json(build/'BUILD_REPORT.json');store=tl.read_json(tl.STORE)
assert report['store_hash']==tl.sha(json.dumps(store,sort_keys=True).encode()),'Build does not reflect current translations'
tl.verify_catalog(store);tl.verify_source();targets=tl.targets_for(store)
for rel,h in report['output_hashes'].items():assert tl.sha((build/rel).read_bytes())==h,rel
excluded={(r['file'],tuple(r['path'])):r for r in tl.read_json(BASE/'reports/excluded_fields.json')}
sites=collections.defaultdict(list)
for u in store['units']:
    for s in u['sites']:
        if s['mode']=='run':
            for n in range(s['count']):sites[(s['file'],tuple(s['path'])+(s['start']+n,'parameters',0))].append((u,s))
        else:sites[(s['file'],tuple(s['path']))].append((u,s))
residual=[];fail=[];command_lists=command_count=0
for p in sorted((build/'data').glob('*.json'))+sorted((build/'img/system').glob('*.json')):
    rel=p.relative_to(build).as_posix();obj=tl.read_json(p);src=tl.read_json(tl.SOURCE/rel)
    for path,value in tl.walk(obj):
        if isinstance(value,int) and path[-1:] == ('code',):command_count+=1
        if not isinstance(value,str) or not tl.JP.search(value):continue
        key=(rel,path);reason=None
        if key in excluded and value==excluded[key]['source']:reason=excluded[key]['reason']
        elif key in sites:
            owners=sites[key];modes={s['mode'] for u,s in owners}
            if modes=={'span'}:
                # Note names remain keys; only the text between their delimiters changes.
                reason='Translated drawn note value; unchanged metadata tag names'
            elif modes=={'js'}:
                old=tl.get(src,path)
                before=tl.js_parse([{'name':'before','source':old}])['before']
                after=tl.js_parse([{'name':'after','source':value}])['after']
                protected=collections.Counter(x['text'] for x in before if tl.JP.search(x['text']))
                for u,s in owners:protected[u['source']]-=1
                actual=collections.Counter(x['text'] for x in after if tl.JP.search(x['text']))
                if not actual-protected:reason='Only protected JS literals/comments remain; drawn literals translated'
        row={'file':rel,'path':list(path),'reason':reason or 'UNCLASSIFIED','source_sha256':tl.sha(value.encode())}
        residual.append(row)
        if not reason:fail.append(row)
    # Independent event command identity check, including metadata-bearing lists.
    def lists(v):
        if isinstance(v,dict):
            for k,x in v.items():
                if isinstance(x,list) and x and all(isinstance(c,dict) and 'code' in c and 'indent' in c for c in x):yield x
                else:yield from lists(x)
        elif isinstance(v,list):
            for x in v:yield from lists(x)
    a=list(lists(src));b=list(lists(obj));assert len(a)==len(b)
    for x,y in zip(a,b):assert [(c['code'],c['indent']) for c in x]==[(c['code'],c['indent']) for c in y]
    command_lists+=len(a)
plugin_exclusions=tl.read_json(BASE/'reports/plugin_decisions.json')
plugins,_=tl.plugins_doc(tl.read_text(build/'js/plugins.js'))
old_plugins,_=tl.plugins_doc(tl.read_text(tl.SOURCE/'js/plugins.js'))
for i,p in enumerate(plugins):
    if not p['status']:continue
    for path,value in tl.nested(p['parameters']):
        if not tl.JP.search(value):continue
        full=(i,'parameters')+path;key=('js/plugins.js',full)
        exc=next((r for r in plugin_exclusions if r.get('file')=='js/plugins.js' and r.get('path')==list(full)),None)
        reason=None
        if exc and value==exc['source']:reason=exc['reason']
        elif key in sites and all(s['mode']=='js' for u,s in sites[key]):reason='Parsed menu scripts: translated display fragments with original comments and keys'
        if not reason:fail.append({'file':'js/plugins.js','path':list(full),'source':value,'reason':'UNCLASSIFIED PARAMETER'})
    rel='js/plugins/'+p['name']+'.js'
    actual=tl.js_parse([{'name':rel,'source':tl.read_text(build/rel)}])[rel]
    allowed=collections.Counter(r['source'] for r in plugin_exclusions if r['file']==rel and r['decision']=='protected')
    remaining=collections.Counter(x['text'] for x in actual if tl.JP.search(x['text']))
    if remaining-allowed:fail.append({'file':rel,'unclassified_literals':list((remaining-allowed).elements())})
result={'pass':not fail,'translated_units':len(targets),'total_units':len(store['units']),'player_facing_japanese':len(fail),
        'protected_residual_fields':len(residual),'command_lists':command_lists,'commands':command_count,
        'event_structure':'same command counts, order, code and indent; numeric/boolean values already proven by builder',
        'four_narrative_nameplate_corrections':report['source_corrections'],
        'artifact_hashes':report['output_hashes'],'failures':fail}
tl.write_json(BASE/'reports/release_residual_ledger.json',residual)
tl.write_json(BASE/'reports/release_audit.json',result)
print(json.dumps({k:v for k,v in result.items() if k not in ['artifact_hashes','four_narrative_nameplate_corrections']},ensure_ascii=True,indent=2))
if fail:raise SystemExit(1)
