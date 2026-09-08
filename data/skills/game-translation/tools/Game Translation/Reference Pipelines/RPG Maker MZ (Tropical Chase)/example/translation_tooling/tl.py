"""Offline manual translation tooling for Tropical Chase (RPG Maker MZ 1.9.0).

All builds read an immutable snapshot and write a new staging directory.
This module has no network or translation-provider code. Installation and release
assembly are separate hash-guarded tools in text_translation/.
"""
from __future__ import annotations
import argparse
import collections
import copy
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from vendor import codes, fileio
from inspect_game import walk, nested

BASE = Path(__file__).resolve().parent
CFG = json.loads((BASE / 'project.json').read_text(encoding='utf-8'))
SOURCE = BASE / 'source'
REPORTS = BASE / 'reports'
STORE = BASE / 'units.json'
PH = re.compile(r'⟦\d+⟧')
JP = re.compile(r'[\u3040-\u3096\u309d-\u30fa\u3400-\u9fff\uff66-\uff9d]')
DB = {'Actors','Armors','Classes','Enemies','Items','Skills','States','Weapons'}
DISPLAY_FIELDS = {'name','nickname','profile','description','message1','message2','message3','message4'}

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def read_text(path):
    # Offsets are measured in the exact source, including CRLF separators.
    return path.read_bytes().decode('utf-8-sig')

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    tmp.replace(path)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def tooling_fingerprint():
    paths=['project.json','tl.py','js_probe.cjs','inspect_game.py','vendor/codes.py','vendor/fileio.py','source_corrections.json']
    return sha(''.join(sha((BASE/p).read_bytes()) for p in paths).encode())

def catalog_fingerprint(units):
    return sha(json.dumps([{k:v for k,v in u.items() if k!='target'} for u in units],sort_keys=True,ensure_ascii=True).encode())

def verify_catalog(store):
    if store.get('tooling_fingerprint')!=tooling_fingerprint():
        raise ValueError('Tooling/config changed since extraction; run extract again')
    if store.get('catalog_fingerprint')!=catalog_fingerprint(store['units']):
        raise ValueError('Catalog metadata changed; only target fields are editable')

def pointer(path):
    return '/' + '/'.join(str(x).replace('~','~0').replace('/','~1') for x in path)

def plugins_doc(text):
    m = re.search(r'\$plugins\s*=\s*(\[.*\])\s*;', text, re.S)
    if not m:
        raise ValueError('Cannot find the shipped $plugins JSON array')
    return json.loads(m[1]), m.span(1)

def js_parse(inputs):
    r = subprocess.run([CFG['node'],'--expose-internals',str(BASE/'js_probe.cjs')],
        input=json.dumps(inputs, ensure_ascii=True), text=True, encoding='utf-8',
        capture_output=True, check=False)
    if r.returncode:
        raise ValueError('JavaScript parse failed: '+r.stderr[:2000])
    return {x['name']: x['literals'] for x in json.loads(r.stdout)}

def get(obj, path):
    for k in path:
        obj = json.loads(obj) if k == '@json' else obj[k]
    return obj

def put(obj, path, value):
    if not path:
        return value
    k, *rest = path
    if k == '@json':
        return json.dumps(put(json.loads(obj), rest, value), ensure_ascii=False, separators=(',',':'))
    obj[k] = put(obj[k], rest, value)
    return obj

def verify_source(game=None):
    manifest = read_json(BASE/'manifest.json')
    root = Path(game).resolve() if game else SOURCE
    for rel, meta in manifest['files'].items():
        p = root/rel
        if not p.is_file() or sha(p.read_bytes()) != meta['sha256']:
            raise ValueError(f'Source fingerprint mismatch: {p}; preserve this project and snapshot before preparing a new game version')
    return manifest

def snapshot(game):
    game = game.resolve()
    if (BASE/'manifest.json').exists():
        verify_source()
        verify_source(game)
        return read_json(BASE/'manifest.json')
    if SOURCE.exists():
        raise ValueError('Unmanifested source directory exists; refusing to overwrite it')
    files = set()
    for folder in ['data','js','fonts','css']:
        files.update(p for p in (game/folder).rglob('*') if p.is_file())
    files.update(game/x for x in ['index.html','package.json'])
    plugins, _ = plugins_doc((game/'js/plugins.js').read_text(encoding='utf-8-sig'))
    for p in plugins:
        if p['status'] and p['name'] == 'RecollectionModeMZ':
            files.add(game/'img/system'/p['parameters']['recoCgSettingList'])
    manifest = {'game_root':str(game),'engine':CFG['engine'],'version':CFG['engine_version'],'files':{}}
    for p in sorted(files):
        if not p.is_file():
            raise ValueError(f'Loaded file is missing: {p}')
        rel = p.relative_to(game).as_posix()
        target = SOURCE/rel
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,target)
        raw=p.read_bytes()
        manifest['files'][rel]={'size':len(raw),'sha256':sha(raw)}
    write_json(BASE/'manifest.json',manifest)
    verify_source()
    return manifest

class Catalog:
    def __init__(self):
        self.units=[]
        self.dedup={}
        self.covered=set()
        self.decisions=[]

    def add(self, kind, raw, sites, *, phase=0, context='', speaker='', unique=False):
        if not isinstance(raw,str) or not raw.strip():
            return
        masked, cmap = codes.mask_codes(raw)
        # This game uses no if()/en() choice directives. Assert that census fact.
        if kind == 'choice' and re.search(r'(?:if|en)\(',raw):
            raise ValueError('New choice condition requires a parser/ruling: '+str(sites))
        if '⟦' in raw or '⟧' in raw:
            raise ValueError('Source collides with placeholder syntax')
        if '\\' in codes._CODE_RE.sub('',raw):
            raise ValueError('Unrecognized control code at '+str(sites))
        if codes.unmask_codes(masked,cmap,pad_inserts=False) != raw:
            raise ValueError('Control-code round trip failed')
        key=(kind,raw)
        if unique or key not in self.dedup:
            uid = ('dialogue:'+sites[0]['file']+pointer(sites[0]['path'])+':'+str(sites[0].get('start',0))) if unique else kind+':'+sha((kind+'\0'+raw).encode())[:20]
            u={'id':uid,'kind':kind,'phase':phase,'source':raw,'text':masked,'codes':cmap,'target':'','sites':[], 'contexts':[]}
            if unique:
                u['speaker']=speaker
            self.units.append(u)
            if not unique:
                self.dedup[key]=u
        else:
            u=self.dedup[key]
            u['phase']=min(u['phase'],phase)
        for site in sites:site['phase']=phase
        u['sites'].extend(sites)
        if context and context not in u['contexts']:
            u['contexts'].append(context)
        for site in sites:
            self.covered.add((site['file'],tuple(site['path'])))

    def value(self, file, obj, path, kind, **kwargs):
        self.add(kind,get(obj,path),[{'file':file,'path':list(path),'mode':'value','original':get(obj,path)}],**kwargs)

def script_sites(cat, file, path, src, lits, kind, context):
    for lit in lits:
        if not lit['text'].strip() or not JP.search(lit['text']):
            continue
        site={'file':file,'path':list(path),'mode':'js','start':lit['start'],'end':lit['end'],
              'original':src[lit['start']:lit['end']],'quote':lit['quote'],'fragment':lit.get('fragment',False)}
        cat.add(kind,lit['text'],[site],phase=2,context=context+' | '+lit['context'])

def event_lists(obj):
    for path,value in walk(obj):
        if isinstance(value,list) and value and all(isinstance(c,dict) and 'code' in c and 'parameters' in c for c in value):
            yield path,value

def extract_events(cat, rel, obj, jsjobs):
    for lp,lst in event_lists(obj):
        i=0
        # Keep real source event metadata as context, without guessing a speaker.
        owner=get(obj,lp[:-1])
        scene=rel+pointer(lp)
        if isinstance(owner,dict) and owner.get('name'):
            scene+=' | '+owner['name']
        while i<len(lst):
            c=lst[i]; p=c['parameters']; code=c['code']; cp=lp+(i,'parameters')
            if code == 101 and len(p)>4:
                cat.value(rel,obj,cp+(4,),'name',phase=1,context=scene+' | native MZ nameplate')
            if code in (401,405):
                start=i
                while i<len(lst) and lst[i]['code']==code:
                    i+=1
                paths=[lp+(j,'parameters',0) for j in range(start,i)]
                source='\n'.join(get(obj,x) for x in paths)
                header=lst[start-1] if start else {}
                speaker=(header.get('parameters',[])+['']*5)[4] if header.get('code')==101 else ''
                site={'file':rel,'path':list(lp),'mode':'run','start':start,'count':i-start,
                      'original':[get(obj,x) for x in paths],'code':code}
                cat.add('dialogue' if code==401 else 'scrolling',source,[site],phase=1,context=scene,speaker=speaker,unique=True)
                cat.covered.update((rel,x) for x in paths)
                continue
            if code == 102:
                for k,label in enumerate(p[0]):
                    sites=[{'file':rel,'path':list(cp+(0,k)),'mode':'value','original':label}]
                    for j in range(i+1,len(lst)):
                        b=lst[j]
                        if b['indent']==c['indent'] and b['code']==404:
                            break
                        if b['indent']==c['indent'] and b['code']==402 and b['parameters'][0]==k:
                            path=lp+(j,'parameters',1)
                            sites.append({'file':rel,'path':list(path),'mode':'value','original':get(obj,path)})
                    cat.add('choice',label,sites,phase=1,context=scene+' | branch index '+str(k))
            if code == 357:
                allowed=CFG['plugin_commands'].get(p[0],{}).get(p[1],[])
                for key in allowed:
                    if key not in p[3]:
                        raise ValueError(f'Missing expected plugin display argument {p[0]}.{key}')
                    cat.value(rel,obj,cp+(3,key),'plugin_text',phase=2,context=scene+' | '+p[0]+'.'+p[1])
            if code == 355 and JP.search(p[0]):
                if not re.fullmatch(r'\$gameVariables\.setValue\(125,\s*"[^"\n]*"\);',p[0]):
                    raise ValueError('Unreviewed Japanese script: '+rel+pointer(cp))
                jsjobs.append((rel,cp+(0,),p[0],'status_value',scene))
            i+=1

def extract_data(cat, jsjobs):
    paths=sorted((SOURCE/'data').glob('*.json'))+sorted((SOURCE/'img/system').glob('*.json'))
    for f in paths:
        rel=f.relative_to(SOURCE).as_posix();obj=read_json(f)
        if f.stem in DB:
            for i,row in enumerate(obj):
                if not row: continue
                for field in sorted(DISPLAY_FIELDS):
                    if isinstance(row.get(field),str):
                        kind='name' if field in {'name','nickname'} else 'description' if field in {'description','profile'} else 'battle_message'
                        cat.value(rel,obj,(i,field),kind,context=rel+':'+str(i)+':'+field)
        if f.stem=='System':
            for path,value in walk(obj):
                if not isinstance(value,str): continue
                if path[0] in {'gameTitle','currencyUnit','terms','armorTypes','weaponTypes','skillTypes','equipTypes','elements'}:
                    cat.value(rel,obj,path,'title' if path[0]=='gameTitle' else 'ui',context=rel+pointer(path))
                elif len(path)==2 and path[0]=='variables' and path[1] in CFG['display_variables']:
                    cat.value(rel,obj,path,'status_label',context='LL_VariableWindow: 200px window, 120px label')
        if re.fullmatch(r'Map\d+',f.stem):
            cat.value(rel,obj,('displayName',),'map_banner',context=rel)
        if rel.startswith('img/system/'):
            for i,row in enumerate(obj):
                cat.value(rel,obj,(i,'title'),'recollection_title',context=rel+':'+str(i))
        for path,value in walk(obj):
            if path and path[-1]=='note' and isinstance(value,str):
                for m in re.finditer(r'<([^:>]+):([^>]*)>',value):
                    if m[1] in CFG['drawn_note_tags']:
                        cat.add('battle_message',m[2],[{'file':rel,'path':list(path),'mode':'span','start':m.start(2),'end':m.end(2),'original':m[2]}],phase=2,context=rel+pointer(path)+' | '+m[1])
        extract_events(cat,rel,obj,jsjobs)
    package=read_json(SOURCE/'package.json')
    cat.value('package.json',package,('window','title'),'title',context='NW.js window caption')
    txt=read_text(SOURCE/'index.html')
    m=re.search(r'<title>(.*?)</title>',txt,re.S)
    if m:
        cat.add('title',html.unescape(m[1]),[{'file':'index.html','path':[],'mode':'html','start':m.start(1),'end':m.end(1),'original':m[1]}],context='HTML window caption')

def extract_plugins(cat, jsjobs):
    plugins,_=plugins_doc((SOURCE/'js/plugins.js').read_text(encoding='utf-8-sig'))
    scans=[]
    for i,p in enumerate(plugins):
        if not p['status']: continue
        name=p['name']; rel='js/plugins/'+name+'.js'
        scans.append({'name':rel,'source':read_text(SOURCE/rel)})
        for path,value in nested(p['parameters']):
            full=(i,'parameters')+path
            last=path[-1] if path else ''
            kind=None; reason=None
            if name=='SceneCustomMenu':
                if last in {'Text','HelpText'}: kind='menu_help' if last=='HelpText' else 'menu_label'
                elif 'ItemDrawScript' in path:
                    jsjobs.append(('js/plugins.js',full,value,'menu_script',name+pointer(path)))
                    reason='JavaScript: only parsed display literals are extracted; expressions/comments are preserved'
                else: reason='Scene IDs, command actions, layout, filters or editor comments'
            elif name=='TorigoyaMZ_Achievement2':
                if last in {'title','description','hint'} or path[0] in {'popupMessage','titleMenuText','achievementMenuHiddenTitle'}:
                    kind='achievement_'+str(last)
                else: reason='Achievement IDs, switches, layout or metadata'
            elif name=='Mano_InputConfig':
                if last=='jp': kind='input_ui'
                else: reason='Alternate English text, input symbols or layout'
            elif name=='RecollectionModeMZ':
                if path[0] in {'recModeSelectWindowRecoTitle','recModeSelectWindowSelectReco','recModeSelectWindowSelectCg','recModeSelectWindowBackTitle','recModeListNeverWatchTextName'}: kind='recollection_ui'
                else: reason='Audio/image filename, data filename, numeric ID or layout'
            elif name=='Keke_VariableActorCommand':
                if path[0]=='用語・自動戦闘': kind='ui'
                else: reason='Plugin parameter enums and lookup keys'
            elif name=='CharacterPictureManager': reason='Picture definition Name is editor metadata; runtime matches actor IDs and game actor names'
            elif name=='SkipAlreadyReadMessage': reason='Original-text sentinel and key bindings, never display wording'
            if kind:
                cat.value('js/plugins.js',plugins,full,kind,phase=2,context=name+pointer(path))
            elif JP.search(value):
                cat.decisions.append({'file':'js/plugins.js','path':list(full),'source':value,'decision':'protected' if reason else 'REVIEW','reason':reason or 'Unclassified Japanese plugin parameter'})
    parsed=js_parse(scans)
    for row in scans:
        rel=row['name']; name=Path(rel).stem;src=row['source']
        for lit in parsed[rel]:
            if not JP.search(lit['text']):continue
            ctx=lit['context']; txt=lit['text']; reason=None
            if name=='Mano_InputConfig' and (txt in {'メニュー/キャンセル','このボタンには%1が割り当て済みです','ボタン表記変更'}):
                script_sites(cat,rel,(),src,[lit],'input_ui',rel+':'+str(lit['line']))
                continue
            if name=='TorigoyaMZ_Achievement2' and ('parseStringParam' in ctx): reason='Fallback overridden by a nonempty configured parameter included in the catalog'
            elif name=='Mano_InputConfig': reason='Plugin installation / developer diagnostic (bilingual where provided)'
            elif name in {'ARTM_PlayerSensorMZ','MKR_PlayerMoveForbid','Recollection_event'}: reason='Plugin error diagnostic, not normal game UI'
            elif lit['parent']=='MemberExpression' or name in {'Keke_VariableActorCommand','MessageSkip','SkipAlreadyReadMessage','MessageWindowHidden','TorigoyaMZ_EnemyHpBar','CustomizeFailureMessage'}: reason='Parameter name, metadata key, parser enum, or help-lookup key; consumer traced in this plugin'
            cat.decisions.append({'file':rel,'line':lit['line'],'source':txt,'context':ctx,'decision':'protected' if reason else 'REVIEW','reason':reason or 'Unclassified Japanese code literal'})
    # Engine/core scripts are parsed as part of the loaded-file census too.
    core=[{'name':p.relative_to(SOURCE).as_posix(),'source':read_text(p)} for p in sorted((SOURCE/'js').glob('*.js')) if p.name!='plugins.js']
    for rel,lits in js_parse(core).items():
        for lit in lits:
            if JP.search(lit['text']):
                # The 170 hits are the engine's name-entry keyboard tables.
                # No code 303 (Name Input Processing) exists in this game's census.
                source=next(x['source'] for x in core if x['name']==rel)
                table_start=source.find('Window_NameInput.JAPAN1 =')
                table_end=source.find('Window_NameInput.prototype.initialize',table_start)
                keyboard=rel=='js/rmmz_windows.js' and table_start<=lit['start']<table_end
                cat.decisions.append({'file':rel,'line':lit['line'],'source':lit['text'],'decision':'protected' if keyboard else 'REVIEW','reason':'Unused engine Japanese name-entry keyboard (no event code 303)' if keyboard else 'Japanese core-script literal'})
    parsed_jobs=js_parse([{'name':str(i),'source':x[2]} for i,x in enumerate(jsjobs)])
    for i,(rel,path,src,kind,ctx) in enumerate(jsjobs):
        script_sites(cat,rel,path,src,parsed_jobs[str(i)],kind,ctx)

def generic_audit(cat):
    """Independent leaf walk; unknown Japanese-bearing paths block readiness."""
    audit=[]
    for f in sorted((SOURCE/'data').glob('*.json'))+sorted((SOURCE/'img/system').glob('*.json')):
        obj=read_json(f);rel=f.relative_to(SOURCE).as_posix()
        for path,value in walk(obj):
            if not isinstance(value,str) or not JP.search(value):continue
            if (rel,path) in cat.covered:
                continue
            reason=None
            if path[-1]=='note':reason='Metadata tags; drawn FailureMessage values extracted separately'
            elif path[-1] in {'characterName','faceName','battlerName','title1Name','title2Name','battleback1Name','battleback2Name','parallaxName','effectName'}:reason='Asset filename'
            elif len(path)>=2 and path[-2] in {'bgm','bgs','se'} and path[-1]=='name':reason='Audio resource filename'
            elif f.stem=='System' and path[0] in {'switches','variables'}:reason='Editor labels and runtime identifiers; only drawn variable IDs 86/102 are whitelisted'
            elif f.stem=='System' and path[0] in {'boat','ship','airship','titleBgm','battleBgm','victoryMe','defeatMe','gameoverMe','sounds','advanced','editor','battleback1Name','battleback2Name'}:reason='Engine/editor configuration or resource reference'
            elif f.stem=='MapInfos' or (f.stem in {'Animations','Tilesets','CommonEvents','Troops'} and path[-1]=='name'):reason='Editor name; no enabled map-name fallback plugin'
            elif path[-1]=='name' and 'events' in path:reason='Map event editor name'
            elif 'parameters' in path:
                pos=len(path)-1-path[::-1].index('parameters'); command=get(obj,path[:pos]);c=command['code']
                if c in {108,408}:reason='Comment/editor instruction; no enabled display-comment consumer in this game'
                elif c in {118,119}:reason='Control-flow label, string-equality target'
                elif c==657:reason='MZ editor echo of preceding plugin command'
                elif c==357:
                    p=command['parameters']
                    if path[pos+1]==2:reason='Plugin command editor label'
                    elif path[-1]=='seName' and p[0]=='LL_InfoPopupWIndow':reason='Popup sound effect asset filename'
                    elif p[0] not in CFG['plugin_commands']:reason='Non-display plugin command arguments (IDs, keys and control actions)'
                elif c in {231,241,245,249,250,261,283,284,322,323,41}:reason='Resource filename'
            audit.append({'file':rel,'path':list(path),'source':value,'decision':'protected' if reason else 'REVIEW','reason':reason or 'Unclassified source-language field'})
    write_json(REPORTS/'excluded_fields.json',audit)
    return audit

def extract():
    manifest=verify_source();cat=Catalog();jsjobs=[]
    extract_data(cat,jsjobs)
    extract_plugins(cat,jsjobs)
    audit=generic_audit(cat)
    cat.units.sort(key=lambda u:(u['phase'],u['kind'],u['id']))
    ids=[u['id'] for u in cat.units]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate unit IDs')
    if STORE.exists():
        old=read_json(STORE);prior={u['id']:u for u in old['units']}
        if len(cat.units)<len(prior):raise ValueError('Extraction shrank; refusing to overwrite existing work')
        for u in cat.units:
            if u['id'] in prior:
                before=prior[u['id']]
                if before['source']!=u['source']:raise ValueError('Source changed under a stable unit ID')
                u['target']=before['target']
    identity=sha(json.dumps(manifest['files'],sort_keys=True).encode())
    write_json(STORE,{'schema':1,'source_manifest':identity,'tooling_fingerprint':tooling_fingerprint(),
                     'catalog_fingerprint':catalog_fingerprint(cat.units),'units':cat.units})
    write_json(REPORTS/'plugin_decisions.json',cat.decisions)
    unknown=[d for d in audit+cat.decisions if d['decision']=='REVIEW']
    summary={'units':len(cat.units),'kinds':dict(collections.Counter(u['kind'] for u in cat.units)),
             'phases':dict(collections.Counter(u['phase'] for u in cat.units)),
             'sites':sum(len(u['sites']) for u in cat.units),'pending_review':len(unknown),
             'source_files':len(manifest['files']),'translated':sum(bool(u['target']) for u in cat.units)}
    write_json(REPORTS/'extraction_summary.json',summary)
    write_json(REPORTS/'pending_review.json',unknown)
    print(json.dumps(summary,indent=2))
    return summary

def targets_for(store):
    """Exercise this actual validator in selftest, including failure cases."""
    targets={};errors=[]
    for u in store['units']:
        target=u['target']
        if not isinstance(target,str):errors.append(u['id']+': target is not a string');continue
        if not target:continue
        expected=PH.findall(u['text']);actual=PH.findall(target)
        if actual != expected:
            errors.append(u['id']+': missing, added, duplicated or reordered placeholders');continue
        if any(x in PH.sub('',target) for x in ['⟦','⟧']):errors.append(u['id']+': invalid placeholder syntax');continue
        if '\\' in target or re.search(r'%\d+',target):errors.append(u['id']+': raw control code; retain masked placeholders');continue
        if JP.search(target):errors.append(u['id']+': Japanese remains in translated text');continue
        restored=codes.unmask_codes(target,u['codes'],pad_inserts=True)
        if codes.code_multiset(restored)!=codes.code_multiset(u['source']):errors.append(u['id']+': restored control codes differ');continue
        if any(s['mode']=='span' for s in u['sites']) and '>' in restored:errors.append(u['id']+': closes a note tag');continue
        targets[u['id']]=restored
    if errors:raise ValueError('\n'.join(errors[:30]))
    return targets

def encode_js(value,site):
    body=json.dumps(value,ensure_ascii=False)[1:-1]
    if site['quote']=="'":body=body.replace("'",r"\'")
    if site['quote']=='`':body=body.replace('`',r'\`').replace('${',r'\${')
    return body if site.get('fragment') else site['quote']+body+site['quote']

def structural_diff(a,b,path=()):
    """Find every changed leaf, including strings, and reject structure drift."""
    if type(a) is not type(b):raise ValueError('Type changed at '+pointer(path))
    if isinstance(a,dict):
        if a.keys()!=b.keys():raise ValueError('Keys changed at '+pointer(path))
        for k in a:yield from structural_diff(a[k],b[k],path+(k,))
    elif isinstance(a,list):
        if len(a)!=len(b):raise ValueError('Array/command count changed at '+pointer(path))
        for i,(x,y) in enumerate(zip(a,b)):yield from structural_diff(x,y,path+(i,))
    elif a!=b:
        if not isinstance(a,str):raise ValueError('Non-string changed at '+pointer(path))
        yield path

def build(output, store=None, phase=2):
    manifest=verify_source();store=store or read_json(STORE)
    if store['source_manifest']!=sha(json.dumps(manifest['files'],sort_keys=True).encode()):raise ValueError('Catalog/source manifest mismatch')
    verify_catalog(store)
    if read_json(REPORTS/'pending_review.json'):raise ValueError('Resolve the pending extraction review before building')
    targets=targets_for(store)
    output=output.resolve()
    if output.exists():raise ValueError('Build destination must be new; stale output is never merged: '+str(output))
    if output==BASE or output==SOURCE or SOURCE in output.parents:raise ValueError('Build cannot overwrite project/source')
    edits=collections.defaultdict(list)
    for u in store['units']:
        if u['id'] in targets:
            for s in u['sites']:
                if s['phase']<=phase:edits[s['file']].append((s,targets[u['id']]))
    corrections=[fix for fix in read_json(BASE/'source_corrections.json')
                 if store['units'][fix['unit_index']]['id'] in targets] if phase>=1 else []
    for fix in corrections:
        if get(read_json(SOURCE/fix['file']),fix['path'])!=fix['expected']:
            raise ValueError('Narrative speaker correction source changed')
        if fix['file'] not in edits:raise ValueError('Correction has no translated owning file')
    # Build to a new tree, never install it automatically.
    output.mkdir(parents=True)
    changed=[];proof=[]
    for rel,meta in manifest['files'].items():
        src=SOURCE/rel;dst=output/rel;dst.parent.mkdir(parents=True,exist_ok=True)
        if rel not in edits:
            shutil.copy2(src,dst);continue
        text=src.read_bytes().decode('utf-8-sig')
        is_plugin=rel=='js/plugins.js'
        is_json=rel.endswith('.json')
        if is_plugin:obj,span=plugins_doc(text)
        elif is_json:obj=read_json(src)
        else:obj=text
        before=copy.deepcopy(obj)
        groups=collections.defaultdict(list)
        allowed=set()
        for site,value in edits[rel]:groups[tuple(site['path'])].append((site,value))
        for path,rows in groups.items():
            current=get(obj,path)
            if rows[0][0]['mode']=='run':
                for s,value in rows:
                    lst=current; start=s['start'];count=s['count'];lines=value.split('\n')
                    if [x['parameters'][0] for x in lst[start:start+count]]!=s['original']:raise ValueError('Message source changed')
                    # Exactly the same command slots: no command index moves.
                    # Extra lines live in the final existing slot, accepted by MZ.
                    parts=lines[:count-1]+['\n'.join(lines[count-1:])] if len(lines)>=count else lines+['']*(count-len(lines))
                    for j,part in enumerate(parts):
                        lst[start+j]['parameters'][0]=part
                        allowed.add(path+(start+j,'parameters',0))
                continue
            if rows[0][0]['mode']=='value':
                values={v for _,v in rows}
                if len(values)!=1:raise ValueError('Conflicting translations at '+rel+pointer(path))
                if current!=rows[0][0]['original']:raise ValueError('Source field changed')
                replacement=rows[0][1]
            else:
                replacement=current;last=len(current)+1
                for s,value in sorted(rows,key=lambda row:row[0]['start'],reverse=True):
                    if s['end']>last:raise ValueError('Overlapping source spans')
                    last=s['start']
                    if current[s['start']:s['end']]!=s['original']:raise ValueError('Source span changed: '+rel+pointer(path))
                    val=encode_js(value,s) if s['mode']=='js' else html.escape(value,quote=False) if s['mode']=='html' else value
                    replacement=replacement[:s['start']]+val+replacement[s['end']:]
            obj=put(obj,path,replacement)
            allowed.add(path[:path.index('@json')] if '@json' in path else path)
        for fix in corrections:
            if fix['file']==rel:
                obj=put(obj,fix['path'],fix['target'])
                allowed.add(tuple(fix['path']))
        diff=list(structural_diff(before,obj))
        if set(diff)-allowed:raise ValueError('Unexpected string edits in '+rel+': '+str(set(diff)-allowed))
        if is_json:
            _,fmt=fileio.load(src);fileio.save(str(dst),obj,fmt)
        else:
            result=text[:span[0]]+json.dumps(obj,ensure_ascii=False,separators=(',',':'))+text[span[1]:] if is_plugin else obj
            raw=result.encode('utf-8');raw=(b'\xef\xbb\xbf'+raw) if src.read_bytes().startswith(b'\xef\xbb\xbf') else raw
            dst.write_bytes(raw)
        changed.append(rel);proof.append({'file':rel,'changed_string_leaves':len(diff)})
    # Reparse edited JS and every edited script field. Compare decoded edited
    # literal values, not just syntax, so escaping errors fail loudly.
    for rel in changed:
        if rel.endswith('.js'):
            js_parse([{'name':rel,'source':(output/rel).read_text(encoding='utf-8-sig')}])
        if rel=='js/plugins.js':obj,_=plugins_doc((output/rel).read_text(encoding='utf-8-sig'))
        elif rel.endswith('.json'):obj=read_json(output/rel)
        else:obj=(output/rel).read_text(encoding='utf-8-sig')
        bypath=collections.defaultdict(list)
        for site,value in edits[rel]:
            if site['mode']=='js':bypath[tuple(site['path'])].append(value)
        for path,expected in bypath.items():
            actual=[l['text'] for l in js_parse([{'name':'patched','source':get(obj,path)}])['patched']]
            if collections.Counter(expected)-collections.Counter(actual):raise ValueError('JS decoded-literal readback failed at '+rel+pointer(path))
    applied=sum(u['id'] in targets and any(s['phase']<=phase for s in u['sites']) for u in store['units'])
    result={'changed_files':changed,'translated_units':applied,'phase':phase,'structure':proof,'source_manifest':store['source_manifest'],
            'tooling_fingerprint':store['tooling_fingerprint'],'store_hash':sha(json.dumps(store,sort_keys=True).encode()),
            'source_corrections':corrections,
            'release_ready':False,'reason':'Staged text build only; translation coverage, fit and game/save testing are separate release gates'}
    result['output_hashes']={rel:sha((output/rel).read_bytes()) for rel in manifest['files']}
    write_json(output/'BUILD_REPORT.json',result)
    return result

def layout_report():
    from fontTools.ttLib import TTFont
    f=TTFont(SOURCE/CFG['layout']['font']);cmap=f.getBestCmap();metrics=f['hmtx'].metrics;upem=f['head'].unitsPerEm
    def width(s):
        t=codes._CODE_RE.sub('',s)
        return sum(metrics[cmap[ord(c)]][0] for c in t if ord(c) in cmap)/upem*CFG['layout']['font_size']
    units=read_json(STORE)['units'];rows=[];missing=collections.Counter()
    for u in units:
        if u['kind']!='dialogue':continue
        lines=u['source'].split('\n')
        missing.update(c for c in codes._CODE_RE.sub('',u['source']) if not c.isspace() and ord(c) not in cmap)
        w=max(map(width,lines),default=0)
        rows.append({'id':u['id'],'source_rows':len(lines),'static_width_px':round(w,2),'over_width':w>CFG['layout']['message_width_px'],'over_conservative_rows':len(lines)>3})
    widths=sorted(x['static_width_px'] for x in rows)
    report={'geometry':CFG['layout'],'source_messages':len(rows),'source_over_width':sum(x['over_width'] for x in rows),'source_over_3_rows':sum(x['over_conservative_rows'] for x in rows),
            'p99_static_width_px':widths[int(len(widths)*.99)],'missing_glyphs':dict(missing),
            'limits':'Static glyph advances only; dynamic substitutions, font effects, plugin windows and in-game rendering require later fit QA. No auto-wrap applied.'}
    write_json(REPORTS/'layout.json',report);f.close();return report

def check():
    verify_source();store=read_json(STORE);targets=targets_for(store)
    verify_catalog(store)
    pending=read_json(REPORTS/'pending_review.json')
    if pending:raise ValueError(f'{len(pending)} unclassified text paths; see reports/pending_review.json')
    result={'units':len(store['units']),'translated':len(targets),'untranslated':len(store['units'])-len(targets),'pending_review':0,'source_integrity':'pass'}
    write_json(REPORTS/'validation.json',result)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('prepare');s.add_argument('--game',type=Path,required=True)
    sub.add_parser('extract');sub.add_parser('check');sub.add_parser('layout')
    b=sub.add_parser('build');b.add_argument('--output',type=Path,required=True);b.add_argument('--phase',type=int,choices=[0,1,2],default=1)
    v=sub.add_parser('verify-game');v.add_argument('--game',type=Path,required=True)
    args=p.parse_args()
    if args.command=='prepare':snapshot(args.game);extract();print(json.dumps(layout_report(),ensure_ascii=True,indent=2))
    elif args.command=='extract':extract()
    elif args.command=='check':print(json.dumps(check(),indent=2))
    elif args.command=='layout':print(json.dumps(layout_report(),ensure_ascii=True,indent=2))
    elif args.command=='build':print(json.dumps(build(args.output,phase=args.phase),indent=2))
    elif args.command=='verify-game':verify_source(args.game);print('All snapshotted game files match the originals.')

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError) as e:
        print('ERROR: '+str(e),file=sys.stderr);sys.exit(1)
