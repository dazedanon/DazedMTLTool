"""Local, resumable authorship records. No translation service or network code."""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import tl

def main():
    store = tl.read_json(tl.STORE)
    tl.verify_catalog(store)
    units = store['units']
    cmd = sys.argv[1]
    if cmd == 'scene':
        needle = sys.argv[2]
        rows = [(n,u) for n,u in enumerate(units) if u['kind']=='dialogue' and any(needle in c for c in u['contexts'])]
        rows.sort(key=lambda row:(row[1]['sites'][0]['file'], repr(row[1]['sites'][0]['path']), row[1]['sites'][0].get('start',0)))
        for n,u in rows:
            print(json.dumps([n,u.get('speaker',''),u['text']],ensure_ascii=False))
    elif cmd == 'read':
        lo, hi = map(int, sys.argv[2:4])
        for n in range(lo, min(hi, len(units))):
            u = units[n]
            print(json.dumps([n, u['kind'], u.get('speaker', ''), u['text'], u['contexts'][:1]], ensure_ascii=False))
    elif cmd == 'apply':
        path = Path(sys.argv[2])
        rows = [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]
        expanded = []
        for row in rows:
            n, target = row[:2]
            if len(row) == 3:
                scope = row[2]['repeat_context']
                seed = units[n]
                matches = [(i,u) for i,u in enumerate(units) if (u['kind'],u.get('speaker'),u['source']) == (seed['kind'],seed.get('speaker'),seed['source']) and any(scope in c for c in u['contexts'])]
                assert any(i == n for i,u in matches), 'Seed outside declared repeat scope'
                expanded.extend([i,target] for i,u in matches)
            else:
                expanded.append([n,target])
        rows = expanded
        assert len({r[0] for r in rows}) == len(rows), 'Duplicate authoring index'
        log = []
        for n, target in rows:
            u = units[n]
            log.append({'id':u['id'], 'source_sha256':tl.sha(u['source'].encode()), 'prior_target':u['target'], 'target':target})
            u['target'] = target
        tl.targets_for(store)
        history = BASE/'manual'/'history'/path.name
        assert not history.exists(), 'Use a new revision filename'
        tl.write_json(history, {'catalog_fingerprint':store['catalog_fingerprint'], 'method':'primary assistant, manually authored; no API', 'records':log})
        tl.write_json(tl.STORE, store)
        print(json.dumps({'applied':len(rows), 'translated':sum(bool(u['target']) for u in units), 'total':len(units)}))
    else:
        raise ValueError(cmd)

if __name__ == '__main__':
    main()
