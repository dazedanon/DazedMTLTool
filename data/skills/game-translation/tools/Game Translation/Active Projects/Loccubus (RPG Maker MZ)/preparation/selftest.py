"""Exercise real preparation/injection gates with synthetic nonsexual text."""
import copy
import json
import subprocess
import tempfile
from pathlib import Path

import tl
from vendor.core import get, read_json, read_text, sha, write_json


def main():
    source = read_json(tl.STORE)
    assert not any(u['target'] for u in source['units']), 'Preparation test expects blank targets'
    manifest = tl.verify_source()
    tl.verify_source(game=True)
    unit_bytes = tl.STORE.read_bytes()
    builds = tl.BASE / 'builds'
    builds.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='preflight-', dir=builds) as scratch:
        scratch = Path(scratch)
        noop = tl.build(scratch / 'noop', source)
        assert not noop['changes']
        for rel, digest in manifest['snapshot_files'].items():
            assert sha((scratch / 'noop' / rel).read_bytes()) == digest
        synthetic = copy.deepcopy(source)
        for unit in synthetic['units']:
            suffix = ' ' if unit['source'].endswith(' ') else ''
            unit['target'] = 'UI "quote" \'apostrophe\' `tick` ${literal}\nNext line ' + ' '.join(tl.PH.findall(unit['text'])) + suffix
        tl.check(synthetic)
        built = tl.build(scratch / 'synthetic', synthetic)
        assert built['translated_units'] == len(synthetic['units'])
        targets = tl.targets_for(synthetic)
        exercised = 0
        dictionary = read_json(scratch / 'synthetic/data/locales/en.json')
        for unit in synthetic['units']:
            for site in unit['sites']:
                expected = targets[unit['id']]
                if site['mode'] == 'dictionary':
                    assert dictionary[site['original']] == expected
                else:
                    obj = tl.read_container(site['file'], scratch / 'synthetic')
                    if site['mode'] == 'js':
                        assert expected in [x['text'] for x in tl.js_parse(obj)]
                    else:
                        assert get(obj, site['path']) == expected
                exercised += 1
        failures = []
        def rejects(label, alter):
            bad = copy.deepcopy(source)
            alter(bad)
            try:
                tl.check(bad)
            except ValueError:
                failures.append(label)
            else:
                raise AssertionError('Gate accepted ' + label)
        token_index = next(i for i, u in enumerate(source['units']) if u['codes'])
        multi_index = next(i for i, u in enumerate(source['units']) if len(u['codes']) > 1)
        def target_at(store, index, target):
            store['units'][index]['target'] = target
        rejects('missing token', lambda s: target_at(s, token_index, 'Test'))
        tokens = tl.PH.findall(source['units'][token_index]['text'])
        rejects('duplicate token', lambda s: target_at(s, token_index, ' '.join(tokens + tokens)))
        tokens = tl.PH.findall(source['units'][multi_index]['text'])
        rejects('reordered tokens', lambda s: target_at(s, multi_index, ' '.join(reversed(tokens))))
        rejects('malformed token', lambda s: target_at(s, 0, 'Test ⟦oops⟧'))
        rejects('residual Chinese', lambda s: target_at(s, 0, '测试'))
        rejects('raw control', lambda s: target_at(s, 0, r'Test\V[1]'))
        rejects('invalid type', lambda s: target_at(s, 0, 17))
        rejects('metadata tamper', lambda s: s['units'][0].update(source='altered'))
        rejects('stale tooling', lambda s: s.update(tooling_fingerprint='stale'))
        rejects('stale manifest', lambda s: s.update(manifest_hash='stale'))
        locale_index = next(i for i, u in enumerate(source['units']) if u['kind'] == 'locale_ui')
        rejects('injected locale tag', lambda s: target_at(s, locale_index, '#Test#'))
        try:
            tl.build(scratch / 'noop', source)
        except ValueError:
            failures.append('existing build destination')
        else:
            raise AssertionError('Existing build overwritten')
        for raw in [r'\F3[sn_01]', r'\F3[\V[1]]', r'\C[2]Test\C[0]', '%1 + %2']:
            masked, mapping = tl.codes.mask_codes(raw)
            assert tl.codes.unmask_codes(masked, mapping, pad_inserts=False) == raw
            if raw.startswith(r'\F3'):
                assert masked == '⟦0⟧', 'Partial portrait token exposed'
        # Re-extraction must preserve real saved targets without introducing work.
        modified = copy.deepcopy(source)
        plain_index = next(i for i, u in enumerate(source['units']) if not u['codes'])
        modified['units'][plain_index]['target'] = 'Synthetic retained target'
        try:
            write_json(tl.STORE, modified)
            tl.extract()
            assert read_json(tl.STORE)['units'][plain_index]['target'] == 'Synthetic retained target'
        finally:
            tl.STORE.write_bytes(unit_bytes)
        tl.extract()
        assert tl.STORE.read_bytes() == unit_bytes
        probe = subprocess.run([tl.config()['node'], '--expose-internals', str(tl.BASE / 'probe_localization.cjs')],
                               capture_output=True, text=True, check=True)
        report = {'empty_build_byte_exact_files': len(manifest['snapshot_files']),
                  'synthetic_units': len(source['units']), 'synthetic_sites': exercised,
                  'rejection_cases': failures, 'reextraction_preserves_targets': True,
                  'repeat_extraction_byte_identical': True,
                  'native_function_probe': json.loads(probe.stdout),
                  'game_files_unchanged': True, 'game_launched': False, 'full_game_ready': False}
    tl.verify_source(game=True)
    write_json(tl.BASE / 'reports/preflight.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
