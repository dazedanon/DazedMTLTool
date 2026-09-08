"""Loccubus offline preparation for reviewed, nonsexual UI text.

No API client, automatic translation, installation, or locale activation.
"""
from __future__ import annotations

import argparse
import atexit
import collections
import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from vendor import codes, fileio
from vendor.core import (encode_js, get, plugins_doc, pointer, put, read_json,
                         read_text, sha, structural_diff, write_json)

BASE = Path(__file__).resolve().parent
def source_root():
    archive = BASE / 'source_snapshot.zip'
    if not archive.exists():
        return BASE / 'source'
    destination = Path(tempfile.mkdtemp(prefix='loccubus-source-'))
    atexit.register(shutil.rmtree, destination, ignore_errors=True)
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            path = Path(item.filename)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Invalid source archive path')
        bundle.extractall(destination)
    return destination


SOURCE = source_root()
STORE = BASE / 'units.json'
CJK = re.compile(r'[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uff66-\uff9d]')
PH = re.compile(r'⟦\d+⟧')


def config():
    return read_json(BASE / 'project.json')


def walk(obj, path=()):
    yield path, obj
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key != '_original':
                yield from walk(value, path + (key,))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from walk(value, path + (index,))


def fingerprint():
    paths = [BASE / n for n in ['tl.py', 'project.json', 'sites.json', 'js_probe.cjs']]
    paths += sorted((BASE / 'vendor').glob('*.py'))
    return sha(''.join(sha(p.read_bytes()) for p in paths).encode())


def catalog_hash(units):
    return sha(json.dumps([{k: v for k, v in u.items() if k != 'target'}
                           for u in units], sort_keys=True).encode())


def js_parse(source):
    result = subprocess.run([config()['node'], '--expose-internals', str(BASE / 'js_probe.cjs')],
                            input=json.dumps([{'name': 'input', 'source': source}]),
                            text=True, encoding='utf-8', capture_output=True, check=False)
    if result.returncode:
        raise ValueError('JavaScript parse failed: ' + result.stderr[:1500])
    return json.loads(result.stdout)[0]['literals']


def verify_source(game=False):
    manifest = read_json(BASE / 'manifest.json')
    if manifest.get('source_archive_hash') and sha((BASE / 'source_snapshot.zip').read_bytes()) != manifest['source_archive_hash']:
        raise ValueError('Immutable source archive changed')
    root = Path(config()['game_root']) if game else SOURCE
    records = manifest['game_files'] if game else manifest['snapshot_files']
    for rel, digest in records.items():
        path = root / rel
        if path.is_symlink() or not path.is_file() or sha(path.read_bytes()) != digest:
            raise ValueError('Source changed: ' + str(path))
    if game:
        actual = {p.relative_to(root).as_posix()
                  for folder in ['data', 'js', 'fonts', 'css']
                  for p in (root / folder).rglob('*') if p.is_file()}
        actual.update(['package.json', 'index.html'])
        if actual != set(records):
            raise ValueError('Game text/runtime file inventory changed')
    return manifest


def read_container(rel, root=SOURCE):
    path = root / rel
    if rel == 'js/plugins.js':
        return plugins_doc(read_text(path))[0]
    if path.suffix == '.json':
        return read_json(path)
    return read_text(path)


def extract():
    manifest = verify_source()
    units, grouped = [], {}
    for site in read_json(BASE / 'sites.json'):
        obj = read_container(site['file'])
        current = get(obj, site['path'])
        if site['mode'] == 'js':
            if current[site['start']:site['end']] != site['original']:
                raise ValueError('Reviewed JS span moved')
        elif current != site['original']:
            raise ValueError('Reviewed source field changed')
        raw = site['source']
        if '⟦' in raw or '⟧' in raw:
            raise ValueError('Source collides with placeholder syntax')
        masked, code_map = codes.mask_codes(raw)
        if codes.unmask_codes(masked, code_map, pad_inserts=False) != raw:
            raise ValueError('Control-code round trip failed')
        key = (site['kind'], raw)
        if key not in grouped:
            unit = {'id': site['kind'] + ':' + sha((site['kind'] + '\0' + raw).encode())[:20],
                    'kind': site['kind'], 'source': raw, 'source_hash': sha(raw.encode()),
                    'text': masked, 'codes': code_map, 'target': '', 'sites': []}
            grouped[key] = unit
            units.append(unit)
        grouped[key]['sites'].append(site)
    units.sort(key=lambda u: (u['kind'], u['id']))
    if STORE.exists():
        previous = {u['id']: u for u in read_json(STORE)['units']}
        if set(previous) - {u['id'] for u in units}:
            raise ValueError('Extraction lost units; refusing to discard work')
        for unit in units:
            if unit['id'] in previous:
                old = previous[unit['id']]
                if old['source_hash'] != unit['source_hash'] or old['sites'] != unit['sites']:
                    raise ValueError('Extraction changed existing source/sites')
                unit['target'] = old['target']
    store = {'schema': 1, 'scope': config()['scope'], 'full_game_ready': False,
             'tooling_fingerprint': fingerprint(), 'catalog_hash': catalog_hash(units),
             'manifest_hash': sha(json.dumps(manifest, sort_keys=True).encode()), 'units': units}
    write_json(STORE, store)
    return check(store)


def targets_for(store):
    targets = {}
    for unit in store['units']:
        target = unit['target']
        if not isinstance(target, str):
            raise ValueError('Target must be a string: ' + unit['id'])
        if not target:
            continue
        if PH.findall(target) != PH.findall(unit['text']):
            raise ValueError('Missing, extra, reordered or duplicated placeholder: ' + unit['id'])
        plain = PH.sub('', target)
        if any(c in plain for c in ['⟦', '⟧', '\\']) or re.search(r'%\d+', plain):
            raise ValueError('Malformed placeholder or raw control code: ' + unit['id'])
        if CJK.search(plain):
            raise ValueError('Chinese/Japanese remains in target: ' + unit['id'])
        if unit['kind'] == 'locale_ui' and '#' in plain:
            raise ValueError('Locale target must contain display text, not new # lookup tags')
        restored = codes.unmask_codes(target, unit['codes'], pad_inserts=True)
        if codes.code_multiset(restored) != codes.code_multiset(unit['source']):
            raise ValueError('Restored control codes differ: ' + unit['id'])
        targets[unit['id']] = restored
    return targets


def check(store=None):
    manifest = verify_source()
    store = store or read_json(STORE)
    if store['tooling_fingerprint'] != fingerprint():
        raise ValueError('Tools/config changed; re-extract before building')
    if store['catalog_hash'] != catalog_hash(store['units']):
        raise ValueError('Catalog metadata changed; only target is editable')
    if store['manifest_hash'] != sha(json.dumps(manifest, sort_keys=True).encode()):
        raise ValueError('Manifest does not match catalog')
    targets = targets_for(store)
    return {'units': len(store['units']), 'sites': sum(len(u['sites']) for u in store['units']),
            'translated': len(targets), 'pending': len(store['units']) - len(targets),
            'source_integrity': 'pass', 'scope': store['scope'], 'full_game_ready': False,
            'api_calls': 0}


def build(output, store=None):
    store = store or read_json(STORE)
    check(store)
    targets = targets_for(store)
    output = output.resolve()
    if output.exists() or output == BASE or SOURCE in output.parents:
        raise ValueError('Build destination must be a fresh directory')
    if BASE / 'builds' not in output.parents:
        raise ValueError('Staged builds must be inside translation_tooling/builds/')
    manifest = verify_source()
    edits = collections.defaultdict(list)
    dictionary = read_json(SOURCE / 'data/locales/en.json')
    dict_expected = {}
    for unit in store['units']:
        if unit['id'] not in targets:
            continue
        target = targets[unit['id']]
        for site in unit['sites']:
            if site['mode'] == 'dictionary':
                key = site['original']
                if key in dict_expected and dict_expected[key] != target:
                    raise ValueError('Conflicting locale translation')
                dict_expected[key] = target
            else:
                edits[site['file']].append((site, target))
    output.mkdir(parents=True)
    for rel in manifest['snapshot_files']:
        destination = output / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE / rel, destination)
    changes = []
    for rel, rows in edits.items():
        before = read_container(rel)
        after = copy.deepcopy(before)
        grouped = collections.defaultdict(list)
        for site, target in rows:
            grouped[tuple(site['path'])].append((site, target))
        allowed = set()
        for path, replacements in grouped.items():
            current = get(after, path)
            mode = replacements[0][0]['mode']
            if mode == 'value':
                if any(s['original'] != current for s, _ in replacements):
                    raise ValueError('Source value mismatch')
                if len({t for _, t in replacements}) != 1:
                    raise ValueError('Conflicting source-site edits')
                replacement = replacements[0][1]
            elif mode == 'js':
                replacement, last = current, len(current) + 1
                for site, target in sorted(replacements, key=lambda row: row[0]['start'], reverse=True):
                    if site['end'] > last or current[site['start']:site['end']] != site['original']:
                        raise ValueError('Overlapping/changed JS spans')
                    last = site['start']
                    replacement = replacement[:site['start']] + encode_js(target, site) + replacement[site['end']:]
                actual = collections.Counter(l['text'] for l in js_parse(replacement))
                if collections.Counter(t for _, t in replacements) - actual:
                    raise ValueError('JS decoded-value readback failed')
            else:
                raise ValueError('Unsupported injection mode: ' + mode)
            after = put(after, path, replacement)
            allowed.add(path[:path.index('@json')] if '@json' in path else path)
        differences = set(structural_diff(before, after))
        if differences - allowed:
            raise ValueError('Unexpected structural or string edits')
        destination = output / rel
        if rel == 'js/plugins.js':
            text = read_text(SOURCE / rel)
            _, span = plugins_doc(text)
            text = text[:span[0]] + json.dumps(after, ensure_ascii=False, separators=(',', ':')) + text[span[1]:]
            js_parse(text)
            destination.write_bytes(text.encode('utf-8'))
        elif rel.endswith('.json'):
            _, fmt = fileio.load(SOURCE / rel)
            fileio.save(str(destination), after, fmt)
        else:
            destination.write_bytes(after.encode('utf-8'))
        changes.append({'file': rel, 'changed_leaves': len(differences)})
    if dict_expected:
        dictionary.update(dict_expected)
        write_json(output / 'data/locales/en.json', dictionary)
        actual = read_json(output / 'data/locales/en.json')
        original = read_json(SOURCE / 'data/locales/en.json')
        if any(actual.get(k) != v for k, v in dict_expected.items()):
            raise ValueError('Locale target readback failed')
        if any(actual.get(k) != v for k, v in original.items() if k not in dict_expected):
            raise ValueError('Existing English dictionary entry changed')
        changes.append({'file': 'data/locales/en.json', 'reviewed_keys': len(dict_expected)})
    report = {'scope': store['scope'], 'translated_units': len(targets), 'changes': changes,
              'tooling_fingerprint': fingerprint(), 'store_hash': sha(json.dumps(store, sort_keys=True).encode()),
              'manifest_hash': store['manifest_hash'], 'release_ready': False, 'locale_enabled': False,
              'output_hashes': {rel: sha((output / rel).read_bytes()) for rel in manifest['snapshot_files']}}
    write_json(output / 'BUILD_REPORT.json', report)
    return report


def import_edits(path):
    store = read_json(STORE)
    check(store)
    updated = copy.deepcopy(store)
    by_id = {u['id']: u for u in updated['units']}
    history, seen = [], set()
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        edit = json.loads(line)
        if edit['id'] in seen:
            raise ValueError('Duplicate edit ID')
        seen.add(edit['id'])
        unit = by_id[edit['id']]
        if edit['source_hash'] != unit['source_hash']:
            raise ValueError('Stale edit source hash')
        history.append({'id': unit['id'], 'source_hash': unit['source_hash'],
                        'previous': unit['target'], 'target': edit['target']})
        unit['target'] = edit['target']
    check(updated)
    if updated == store:
        return {'changed': 0}
    archive = BASE / 'history'
    archive.mkdir(exist_ok=True)
    transaction = {'before': sha(STORE.read_bytes()), 'edits': history}
    write_json(archive / (sha(json.dumps(transaction, sort_keys=True).encode()) + '.json'), transaction)
    write_json(STORE, updated)
    return {'changed': len(history)}


def export_batch(output, limit):
    store = read_json(STORE)
    check(store)
    if output.exists():
        raise ValueError('Batch output already exists')
    units = [u for u in store['units'] if not u['target']][:limit]
    glossary = read_json(BASE / 'glossary.json')
    current_text = '\n'.join(u['source'] for u in units)
    def matches(term):
        if re.fullmatch(r'[\u3400-\u9fff]+', term):
            return bool(re.search(r'(?<![\u3400-\u9fff])' + re.escape(term) + r'(?![\u3400-\u9fff])', current_text))
        if re.fullmatch(r'[\u30a0-\u30ff]+', term):
            return bool(re.search(r'(?<![\u30a0-\u30ff])' + re.escape(term) + r'(?![\u30a0-\u30ff])', current_text))
        return term in current_text
    matched = {'names': {k: v for k, v in glossary['names'].items()
                         if any(matches(t) for t in [k] + v.get('aliases', []))},
               'terms': {k: v for k, v in glossary['terms'].items() if matches(k)},
               'do_not_translate': [t for t in glossary['do_not_translate'] if matches(t)]}
    result = {'scope': store['scope'], 'source_language': 'zh-CN', 'target_language': 'en',
              'instructions': {n: read_text(BASE / n) for n in
                               ['translation_frame.md', 'game_prompt.md', 'quirks.md', 'field_instructions.md']},
              'glossary': matched,
              'glossary_hash': sha((BASE / 'glossary.json').read_bytes()),
              'units': [{'id': u['id'], 'source_hash': u['source_hash'], 'text': u['text'],
                         'kind': u['kind'], 'contexts': [s['context'] for s in u['sites']]} for u in units],
              'output_contract': 'JSONL: {"id":"...","source_hash":"...","target":"..."}'}
    write_json(output, result)
    return {'units': len(units), 'output': str(output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('extract')
    commands.add_parser('check')
    commands.add_parser('verify-game')
    cmd = commands.add_parser('build')
    cmd.add_argument('--output', type=Path, required=True)
    cmd = commands.add_parser('import-edits')
    cmd.add_argument('path', type=Path)
    cmd = commands.add_parser('export-batch')
    cmd.add_argument('--output', type=Path, required=True)
    cmd.add_argument('--limit', type=int, default=30)
    args = parser.parse_args()
    if args.command == 'extract':
        result = extract()
    elif args.command == 'check':
        result = check()
    elif args.command == 'verify-game':
        verify_source(game=True)
        result = {'game_files_unchanged': True}
    elif args.command == 'build':
        result = build(args.output)
    elif args.command == 'import-edits':
        result = import_edits(args.path)
    else:
        if args.limit < 1:
            raise ValueError('Batch limit must be positive')
        result = export_batch(args.output, args.limit)
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        sys.exit(1)
