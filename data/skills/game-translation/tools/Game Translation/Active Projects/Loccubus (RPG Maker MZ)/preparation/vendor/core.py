"""Offline JSON/span primitives adapted from the Tropical Chase reference."""
import hashlib
import json
import re

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

def pointer(path):
    return '/' + '/'.join(str(x).replace('~','~0').replace('/','~1') for x in path)

def plugins_doc(text):
    m = re.search(r'\$plugins\s*=\s*(\[.*\])\s*;', text, re.S)
    if not m:
        raise ValueError('Cannot find the shipped $plugins JSON array')
    return json.loads(m[1]), m.span(1)

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
