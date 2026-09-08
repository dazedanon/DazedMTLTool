"""Read-only inventory; does not import or execute game/plugin code."""
import collections
import json
import re
import sys
from pathlib import Path
from vendor import js_strings

PROJECT = Path(__file__).resolve().parent
ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else (PROJECT/'source' if (PROJECT/'source').exists() else PROJECT.parent)
OUT = Path(__file__).resolve().parent / 'reports'
JP = re.compile(r'[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9d]')

def walk(value, path=()):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, path + (key,))
    elif isinstance(value, list):
        for key, child in enumerate(value):
            yield from walk(child, path + (key,))

def nested(value, path=()):
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            yield from nested(parsed, path + ('@json',))
        else:
            yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from nested(child, path + (key,))
    elif isinstance(value, list):
        for key, child in enumerate(value):
            yield from nested(child, path + (key,))

def main():
    OUT.mkdir(exist_ok=True)
    plugins_text = (ROOT/'js/plugins.js').read_text(encoding='utf-8-sig')
    plugins = json.loads(re.search(r'\$plugins\s*=\s*(\[.*\])\s*;', plugins_text, re.S)[1])
    enabled = [p for p in plugins if p['status']]
    counts, byfile, jpcode = collections.Counter(), {}, collections.defaultdict(list)
    cmd357, headers, escapes, notes = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    variables = []
    for f in sorted((ROOT/'data').glob('*.json')):
        obj = json.loads(f.read_text(encoding='utf-8-sig'))
        local = collections.Counter()
        for ptr, val in walk(obj):
            if isinstance(val, dict) and isinstance(val.get('code'), int) and 'parameters' in val:
                c, p = val['code'], val['parameters']
                counts[c] += 1
                local[c] += 1
                if c == 357:
                    cmd357[(p[0], p[1])] += 1
                if c == 101:
                    headers['all'] += 1
                    headers['speaker'] += int(len(p)>4 and bool(p[4]))
                    headers['face'] += int(bool(p[0]))
                if c == 122 and len(p)>4 and p[3] == 4:
                    variables.append({'file':f.name, 'path':ptr, 'params':p})
                if c != 401 and JP.search(json.dumps(p, ensure_ascii=False)):
                    jpcode[c].append({'file':f.name,'path':ptr,'params':p})
            if isinstance(val,str):
                if ptr and ptr[-1] == 'note':
                    for tag in re.findall(r'<([^:>]+)(?::[^>]*)?>',val):
                        notes[tag] += 1
                for code in re.findall(r'\\[A-Za-z]+[1-8]?|\\[.|!^<>{}$]|%\d+',val):
                    escapes[code] += 1
        byfile[f.name] = dict(local)
    paramrows, literals = [], []
    for p in enabled:
        for ptr, val in nested(p['parameters']):
            if JP.search(val):
                paramrows.append({'plugin':p['name'],'path':ptr,'text':val})
        f = ROOT/'js/plugins'/ (p['name']+'.js')
        src, hits = js_strings.scan(f)
        lines = src.splitlines()
        for h in hits:
            h.update(plugin=p['name'], context='\n'.join(lines[max(0,h['line']-2):h['line']+1]))
            literals.append(h)
    report = {'counts':dict(counts),'by_file':byfile,'headers':dict(headers),
              'commands357':[{'plugin':p,'command':c,'count':n} for (p,c),n in cmd357.most_common()],
              'jp_event_fields':dict(jpcode),'script_variables':variables,'notes':dict(notes),
              'escape_names':dict(escapes),'enabled':[p['name'] for p in enabled],
              'disabled':[p['name'] for p in plugins if not p['status']]}
    for name, value in [('census',report),('plugin_parameters_review',paramrows),('plugin_literals_review',literals)]:
        (OUT/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'data_files':len(byfile),'codes':dict(counts),'headers':dict(headers),
                      'enabled_plugins':len(enabled),'plugin_parameter_leaves':len(paramrows),
                      'plugin_jp_literals':len(literals),'script_variable_assignments':len(variables),
                      'commands357':report['commands357'],'escapes':dict(escapes),'notes':dict(notes)},ensure_ascii=True,indent=2))

if __name__ == '__main__':
    main()
