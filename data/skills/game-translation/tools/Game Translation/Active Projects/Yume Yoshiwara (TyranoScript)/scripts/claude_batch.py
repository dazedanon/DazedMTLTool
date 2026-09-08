"""Offline request preparation and explicit, resumable Claude Message Batches.

Adapted from the AjinSyoujyo reference's submit/status/fetch architecture.
No command falls back to a synchronous, full-price generation.
"""
from __future__ import annotations

import collections
import contextlib
import datetime
import json
import math
import os
from pathlib import Path

import project as p

RULES = '''Translate the supplied Japanese game text into natural English.
Return ONLY {"t":{"0":"English",...}}, with every requested numeric ID exactly once.
Do not return context-only lines. Preserve the exact sequence of numbered ⟦n⟧
placeholders; they stand for engine controls, HTML, substitutions, or line breaks.
Never add markup, physical newlines, or scenario commands. Keep spaces around word
substitutions, except before possessive apostrophes or hyphens. Keep fragment edge
spaces when grammar needs them. Preserve meaning, tone, numbers, and character
identity; add no events or details. Keep short UI labels concise. Use the locked
glossary spelling for names. Do not merge speakers or reveal unknown identities.
Translate only supplied content that is permissible to translate. Do not produce
sexual content involving minors; return null for a unit requiring that exclusion.
Each record supplies its kind, speaker, scene, and optional expression context.
Values marked display_value are display copies: their underlying state keys are
preserved locally. Translate their visible meaning, never invent technical syntax.
Use ordinary English punctuation. Do not open prose with ; * @ # or _.
The reply is a compact ID-to-string map; no notes, speaker fields, or explanations.
'''


def config():
    return p.read_json(p.ROOT/'config.json')


def store():
    path = p.ROOT/'translations.json'
    return p.read_json(path) if path.exists() else {'schema':1, 'translations':{}, 'provenance':{}}


def estimate_tokens(text):
    # Mixed-script proxy from the shared reference. Explicitly not an API count.
    japanese = sum(ord(c) >= 0x3000 for c in text)
    return math.ceil(japanese * 1.1 + (len(text)-japanese) * 0.27)


def prefix():
    glossary = p.read_json(p.ROOT/'glossary.json')
    compact = {'names':{k:{a:v for a,v in row.items() if a in ('en','gender','role','register','aliases')}
                        for k,row in glossary['names'].items()}, 'terms':glossary.get('terms',{})}
    return RULES + '\n' + (p.ROOT/'game_prompt.md').read_text(encoding='utf-8') + '\n' + json.dumps(compact,ensure_ascii=False)


def make_requests(phase='all', limit=None):
    catalog, units = p.load_catalog()
    cfg = config()
    completed = store()['translations']
    selected = [u for u in units if u.id not in completed and
                (phase=='all' or (u.kind=='name') == (phase=='names'))]
    # Names first; dialogue retains source order and file/scene metadata.
    selected.sort(key=lambda u: (0 if u.kind=='name' else 1 if u.kind in ('dialogue','punct') else 2,
                                 u.sites[0].file if u.kind in ('dialogue','punct') else '',u.sites[0].order))
    groups = []
    current = []
    current_file = None
    chars = 0
    for unit in selected:
        file = unit.sites[0].file if unit.kind in ('dialogue','punct') else '@'+('names' if unit.kind=='name' else 'ui')
        if current and (file != current_file or len(current)>=cfg['units_per_request'] or chars+len(unit.src)>cfg['source_chars_per_request']):
            groups.append(current)
            current=[];chars=0
        current_file=file
        current.append(unit);chars+=len(unit.src)
    if current:
        groups.append(current)
    if limit is not None:
        groups=groups[:limit]
    system = prefix()
    requests=[]
    previous_by_file={}
    for group in groups:
        source_file=group[0].sites[0].file
        context=previous_by_file.get(source_file,[])[-3:] if group[0].kind in ('dialogue','punct') else []
        records=[]
        for index,u in enumerate(group):
            records.append({'id':str(index),'kind':u.kind,'speaker':u.speaker,'scene':u.scene,
                            'source':u.src,'expression_context':u.sites[0].context[:400]})
        body=json.dumps({'context_only':context,'translate':records},ensure_ascii=False,separators=(',',':'))
        estimated_output=math.ceil(sum(len(u.src) for u in group)*0.27*cfg['output_ratio'] + len(group)*8)
        max_tokens=min(cfg['max_output_tokens'],max(2048,math.ceil(estimated_output*2+1024)))
        block={'type':'text','text':system}
        if cfg['cache_ttl']:
            block['cache_control']={'type':'ephemeral','ttl':cfg['cache_ttl']}
        params={'model':cfg['model'],'max_tokens':max_tokens,'thinking':{'type':'adaptive'},
                'output_config':{'effort':cfg['effort']},'system':[block],
                'messages':[{'role':'user','content':body}]}
        # IDs and logical payload both participate; a changed instruction is a new request.
        key=p.digest({'ids':[u.id for u in group],'params':params,'schema':1})
        requests.append({'custom_id':'yy_'+key[:48], 'params':params,
                         'unit_ids':[u.id for u in group], 'output_estimate':estimated_output})
        previous_by_file[source_file]=[{'speaker':u.speaker,'source':u.src,'scene':u.scene} for u in group]
    return catalog,requests


def estimate(requests):
    cfg=config()
    n=len(requests)
    prefix_tokens=estimate_tokens(prefix())
    fresh=sum(estimate_tokens(r['params']['messages'][0]['content']) for r in requests)
    output=sum(r['output_estimate'] for r in requests)
    rate_in=cfg['pricing']['batch_input_per_million']
    rate_out=cfg['pricing']['batch_output_per_million']
    write_multiplier=2 if cfg['cache_ttl']=='1h' else 1.25
    def cost(hits, ratio=1):
        cached=prefix_tokens*((n-hits)*write_multiplier+hits*.1) if cfg['cache_ttl'] else n*prefix_tokens
        return round(((fresh+cached)*rate_in+output*ratio*rate_out)/1e6,4)
    uncached=round(((fresh+n*prefix_tokens)*rate_in+output*rate_out)/1e6,4)
    expected=cost(max(n-1,0)*.4)
    cold=cost(0)
    guard=round(cost(0,1.6)*1.3*1.15,2)
    return {'model':cfg['model'],'effort':cfg['effort'],'thinking':'adaptive',
            'cache_ttl':cfg['cache_ttl'],'requests':n,'units':sum(len(r['unit_ids']) for r in requests),
            'prefix_tokens_per_request':prefix_tokens,'fresh_input_tokens':fresh,
            'input_tokens_without_cache':fresh+n*prefix_tokens,'estimated_output_tokens':output,
            'usd':{'optimistic_cache':cost(max(n-1,0)), 'assumed_40_percent_cache_hits':expected,
                   'all_cache_misses':cold,'no_cache':uncached,'planning_budget_with_retry_margin':guard},
            'method':'mixed-script local proxy; compact map output ratio 1.38 plus per-ID JSON overhead',
            'uncertainty':'Output/thinking and cache hit rate are estimates. Planning budget allows 1.6x output, 1.3x token proxy, and 15% retries.',
            'time':'Plan approximately 1-4 hours per batch after submission; provider may run up to 24 hours or expire requests.',
            'pricing_checked':cfg['pricing']['checked'],'pricing_source':cfg['pricing']['source']}


def prepare(phase,limit=None):
    catalog,requests=make_requests(phase,limit)
    if not requests:
        raise ValueError('No untranslated units selected')
    payload={'schema':1,'phase':phase,'source_fingerprint':catalog['source_fingerprint'],
             'catalog_fingerprint':p.digest(catalog), 'config_fingerprint':p.digest(config()),
             'instructions_fingerprint':p.digest(prefix()), 'requests':requests,'estimate':estimate(requests)}
    ident=p.digest(payload)[:16]
    folder=p.ROOT/'runs'/ident
    while (folder/'fetch_report.json').exists() and p.read_json(folder/'fetch_report.json')['failed_requests']:
        payload['retry_of']=ident
        ident=p.digest(payload)[:16]
        folder=p.ROOT/'runs'/ident
    path=folder/'manifest.json'
    if path.exists() and p.read_json(path)!=payload:
        raise ValueError('immutable run manifest conflict')
    if not path.exists():
        p.write_json(path,payload)
    return {'run':ident,'manifest':str(path),'estimate':payload['estimate']}


@contextlib.contextmanager
def lock(folder):
    # O_EXCL is nonblocking across independent Python processes on Windows.
    path=folder/'operation.lock'
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    try:
        os.write(fd,str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink()


def get_run(run):
    if not run or any(c not in '0123456789abcdef' for c in run) or len(run)!=16:
        raise ValueError('run must be the 16-character ID returned by prepare')
    folder=p.ROOT/'runs'/run
    return folder,p.read_json(folder/'manifest.json')


def client(expected=None):
    import anthropic
    key=os.getenv('ANTHROPIC_API_KEY')
    if not key:
        raise ValueError('Set ANTHROPIC_API_KEY in the current environment; keys are never stored in the project.')
    endpoint=os.getenv('ANTHROPIC_BASE_URL','https://api.anthropic.com').rstrip('/')
    identity={'endpoint':endpoint,'credential_sha256':p.digest(key.encode())}
    if expected is not None and expected!=identity:
        raise ValueError('Batch credential or endpoint changed; restore the original environment.')
    # Disable automatic POST retries: a lost submission response is ambiguous.
    return anthropic.Anthropic(api_key=key,base_url=endpoint,max_retries=0,timeout=120),identity


def split_requests(requests,max_bytes=240_000_000,max_count=90_000):
    parts=[];current=[];size=32
    for r in requests:
        request={'custom_id':r['custom_id'],'params':r['params']}
        length=len(json.dumps(request,ensure_ascii=False).encode('utf-8'))+128
        if length+32>max_bytes:
            raise ValueError('A single request exceeds the batch byte limit')
        if current and (len(current)>=max_count or size+length>max_bytes):
            parts.append(current);current=[];size=32
        current.append(request);size+=length
    if current:parts.append(current)
    return parts


def submit(run):
    folder,manifest=get_run(run)
    catalog,_=p.load_catalog()
    if p.digest(catalog)!=manifest['catalog_fingerprint'] or p.digest(config())!=manifest['config_fingerprint'] or p.digest(prefix())!=manifest['instructions_fingerprint']:
        raise ValueError('Prepared run is stale; re-prepare with the current source and instructions.')
    if p.read_json(p.REPORTS/'blockers.json'):
        raise ValueError('Resolve extraction blockers before submission')
    if manifest['phase']=='all':
        raise ValueError('Submit names first, lock glossary, then prepare text. all is for estimation only.')
    if manifest['phase']=='text' and any(not r.get('en') for r in p.read_json(p.ROOT/'glossary.json')['names'].values()):
        raise ValueError('Glossary contains unresolved names; finish the names phase first.')
    if len({r['params']['model'] for r in manifest['requests']})!=1:
        raise ValueError('Mixed models in one run')
    if manifest['estimate']['usd']['planning_budget_with_retry_margin']>config()['submission_budget_usd']:
        raise ValueError('Run exceeds the configured submission planning budget')
    with lock(p.ROOT):
        state_path=folder/'state.json'
        state=p.read_json(state_path) if state_path.exists() else {'jobs':[], 'pending':None}
        if state['pending']:
            raise ValueError('Previous submission outcome is uncertain. Reconcile its custom IDs with the provider before retrying.')
        # Refuse overlaps even if another prepared manifest used different chunking.
        requested={u for r in manifest['requests'] for u in r['unit_ids']}
        for path in (p.ROOT/'runs').glob('*/state.json'):
            if path==state_path:continue
            prior=p.read_json(path)
            if (prior.get('jobs') or prior.get('pending')) and not (path.parent/'fetch_report.json').exists():
                prior_manifest=p.read_json(path.parent/'manifest.json')
                prior_ids={u for r in prior_manifest['requests'] for u in r['unit_ids']}
                if requested & prior_ids:
                    raise ValueError('Units overlap an existing submitted run; fetch that run before preparing a retry.')
        api,identity=client(state.get('identity'))
        state['identity']=identity
        submitted={i for job in state['jobs'] for i in job['custom_ids']}
        remaining=[r for r in manifest['requests'] if r['custom_id'] not in submitted]
        for part in split_requests(remaining):
            ids=[r['custom_id'] for r in part]
            state['pending']={'custom_ids':ids,'at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
            p.write_json(state_path,state)  # Record intention before the network boundary.
            response=api.messages.batches.create(requests=part)
            state['jobs'].append({'id':response.id,'custom_ids':ids})
            state['pending']=None
            p.write_json(state_path,state)  # Checkpoint before attempting the next split.
            with (folder/'history.jsonl').open('a',encoding='utf-8') as fh:
                fh.write(json.dumps(state['jobs'][-1])+'\n')
        return {'run':run,'jobs':state['jobs']}


def status(run):
    folder,_=get_run(run)
    state=p.read_json(folder/'state.json')
    api,_=client(state['identity'])
    return [api.messages.batches.retrieve(job['id']).model_dump(mode='json') for job in state['jobs']]


def parse_reply(text,expected):
    obj=p.strict_json(text)
    if set(obj)!={'t'} or not isinstance(obj['t'],dict) or set(obj['t'])!=set(expected):
        raise ValueError('Reply must contain exactly the requested IDs in a t map')
    return obj['t']


def import_mapping(mapping,provenance,overwrite=False):
    _,units=p.load_catalog()
    byid={u.id:u for u in units}
    unknown=set(mapping)-set(byid)
    if unknown:raise ValueError(f'Unknown IDs: {sorted(unknown)[:3]}')
    errors={uid:p.validate_text(byid[uid],value) for uid,value in mapping.items()}
    errors={k:v for k,v in errors.items() if v}
    if errors:raise ValueError(json.dumps(errors,ensure_ascii=False))
    current=store()
    for uid,value in mapping.items():
        if uid in current['translations'] and current['translations'][uid]!=value and not overwrite:
            raise ValueError('Import would overwrite a translation; use an explicitly reviewed correction.')
    for uid,value in mapping.items():
        current['translations'][uid]=value
        current['provenance'][uid]=provenance
    p.write_json(p.ROOT/'translations.json',current)
    return len(mapping)


def lock_names():
    _,units=p.load_catalog()
    values=store()['translations']
    glossary=p.read_json(p.ROOT/'glossary.json')
    changed=0
    for u in units:
        if u.kind=='name' and u.id in values:
            row=glossary['names'].setdefault(u.src,{'gender':'unknown','role':'nameplate','register':'follow scene','aliases':[]})
            if row.get('en') and row['en']!=values[u.id]:
                raise ValueError(f'Name disagrees with locked glossary: {u.src}')
            row['en']=values[u.id]
            changed+=1
    missing=[k for k,v in glossary['names'].items() if not v.get('en')]
    p.write_json(p.ROOT/'glossary.json',glossary)
    return {'locked_name_units':changed,'unresolved':missing}


def fetch(run):
    folder,manifest=get_run(run)
    catalog,_=p.load_catalog()
    if p.digest(catalog)!=manifest['catalog_fingerprint']:
        raise ValueError('Catalog changed after submission; restore the frozen catalog before fetching.')
    with lock(p.ROOT):
        state=p.read_json(folder/'state.json')
        api,_=client(state['identity'])
        for job in state['jobs']:
            if api.messages.batches.retrieve(job['id']).processing_status!='ended':
                raise ValueError('Batch still processing; fetch again after it ends.')
        rows=[]
        for job in state['jobs']:
            rows.extend(r.model_dump(mode='json') for r in api.messages.batches.results(job['id']))
        p.write_json(folder/'results.json',rows)  # exact fresh snapshot; never mix runs
        request_map={r['custom_id']:r for r in manifest['requests']}
        _,units=p.load_catalog();byid={u.id:u for u in units}
        seen=set();accepted={};failed={};usage=collections.Counter()
        for row in rows:
            rid=row['custom_id']
            if rid in seen or rid not in request_map:
                raise ValueError('Duplicate or unknown custom_id in results')
            seen.add(rid);result=row['result']
            if result['type']!='succeeded':failed[rid]=result['type'];continue
            message=result['message']
            usage.update({k:message.get('usage',{}).get(k,0) or 0 for k in
                          ('input_tokens','output_tokens','cache_creation_input_tokens','cache_read_input_tokens')})
            if message.get('stop_reason')!='end_turn':failed[rid]=message.get('stop_reason');continue
            text=''.join(b['text'] for b in message['content'] if b['type']=='text')
            ids=request_map[rid]['unit_ids']
            try:
                values=parse_reply(text,[str(i) for i in range(len(ids))])
                staged={uid:values[str(i)] for i,uid in enumerate(ids)}
                errors={uid:p.validate_text(byid[uid],v) for uid,v in staged.items()}
                errors={k:v for k,v in errors.items() if v}
                if errors:raise ValueError(json.dumps(errors))
                accepted.update(staged)
            except (ValueError,TypeError) as exc:
                failed[rid]=str(exc)
        for rid in set(request_map)-seen:failed[rid]='missing-result'
        applied=import_mapping(accepted,{'run':run,'model':manifest['estimate']['model']})
        rates=config()['pricing'];wm=2 if manifest['estimate']['cache_ttl']=='1h' else 1.25
        bill=((usage['input_tokens']+usage['cache_creation_input_tokens']*wm+usage['cache_read_input_tokens']*.1)*rates['batch_input_per_million']+usage['output_tokens']*rates['batch_output_per_million'])/1e6
        report={'accepted_units':applied,'failed_requests':failed,'usage':dict(usage),'billed_usd_from_usage':round(bill,5)}
        p.write_json(folder/'fetch_report.json',report)
        return report
