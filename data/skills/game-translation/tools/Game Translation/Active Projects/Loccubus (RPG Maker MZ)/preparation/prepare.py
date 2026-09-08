"""Reproducible offline inventory and immutable general-UI snapshot.

Story content is counted by location only and is never added to the work queue.
"""
import collections
import json
import re
import shutil
from pathlib import Path

import tl
from vendor.core import get, plugins_doc, read_json, read_text, sha, write_json

BASE = Path(__file__).resolve().parent
GAME = BASE.parent
UI_FILES = ['data/MUUI/MUUI_9cundang.json', 'data/MUUI/MUUI_9-1dudang.json',
            'data/MUUI/MUUI_confirmation_skip.json']
PARAMETERS = {'UI/BY_Toast': ['goldName', 'expName'],
              'USES/NovelGameUI': ['limitSkipName'],
              'USE/XR_FixName': ['menuWord', 'titleText', 'nameWord', 'titleWord']}
SYSTEM_FIELDS = ['terms', 'currencyUnit', 'armorTypes', 'weaponTypes', 'skillTypes',
                 'elements', 'equipTypes']


def main():
    if (BASE / 'manifest.json').exists():
        tl.verify_source(game=True)
        tl.verify_source()
        print(json.dumps(tl.extract(), indent=2))
        return
    if (BASE / 'source').exists():
        raise ValueError('Unmanifested snapshot exists; refusing to replace it')
    paths = sorted({p for folder in ['data', 'js', 'fonts', 'css']
                    for p in (GAME / folder).rglob('*') if p.is_file()}
                   | {GAME / 'package.json', GAME / 'index.html'})
    hashes = {p.relative_to(GAME).as_posix(): sha(p.read_bytes()) for p in paths}
    plugins, _ = plugins_doc(read_text(GAME / 'js/plugins.js'))
    sites, omitted_ui = [], []
    system = read_json(GAME / 'data/System.json')
    for path, value in tl.walk(system):
        if path and path[0] in SYSTEM_FIELDS and isinstance(value, str) and value.strip():
            sites.append({'file': 'data/System.json', 'path': list(path), 'mode': 'value',
                          'original': value, 'source': value, 'kind': 'system_ui', 'phase': 0,
                          'context': 'Stock MZ System display field ' + tl.pointer(path)})
    for rel in UI_FILES:
        for path, obj in tl.walk(read_json(GAME / rel)):
            if not isinstance(obj, dict) or obj.get('type') != 'text':
                continue
            value = obj.get('content', '')
            style = obj.get('style', {})
            if style.get('bindings') or not (value.startswith('#') and value.endswith('#')):
                omitted_ui.append({'file': rel, 'path': list(path + ('content',)),
                                   'reason': 'Runtime-bound value or nonlocalized numeric/template preview'})
                continue
            sites.append({'file': rel, 'path': list(path + ('content',)),
                          'original': value, 'source': value[1:-1], 'mode': 'dictionary',
                          'kind': 'locale_ui', 'phase': 0,
                          'context': 'MUUI general UI component ' + str(obj['id']) + ' in ' + rel,
                          'layout': {'transform': obj.get('transform', {}), 'style': {
                              key: style.get(key) for key in ['fontFamily', 'fontSize', 'autoWrap',
                                                           'clipOverflow', 'outlineWidth', 'letterSpacing']}}})
    for index, plugin in enumerate(plugins):
        if not plugin['status']:
            continue
        for key in PARAMETERS.get(plugin['name'], []):
            value = plugin['parameters'][key]
            sites.append({'file': 'js/plugins.js', 'path': [index, 'parameters', key],
                          'mode': 'value', 'original': value, 'source': value,
                          'kind': 'plugin_ui', 'phase': 2,
                          'context': plugin['name'] + '.' + key + ' (display parameter)'})
    helper = 'js/plugins/UI/MU_Internal/MU_SavefileHelper.js'
    script = read_text(GAME / helper)
    for literal in tl.js_parse(script):
        if literal['start'] >= 7000 or literal['text'] not in {'自动存档', '存档 ', '已存档', '空'}:
            continue
        if literal.get('tagged') or literal.get('review_required'):
            raise ValueError('Save helper uses an unreviewed tagged template')
        sites.append({'file': helper, 'path': [], 'mode': 'js',
                      'original': script[literal['start']:literal['end']], 'source': literal['text'],
                      'start': literal['start'], 'end': literal['end'], 'quote': literal['quote'],
                      'fragment': literal.get('fragment', False), 'kind': 'save_ui', 'phase': 2,
                      'context': 'Runtime savefile name/status display: ' + literal['context']})
    snapshot = {s['file'] for s in sites} | {'data/locales/en.json', 'js/plugins/MUUI_Localization.js',
               'js/rmmz_windows.js', 'js/rmmz_objects.js', 'js/rmmz_managers.js',
               'js/plugins/BY/BY_MessageWindow.js', 'js/plugins/BY/BY_CommonEventLocale.js',
               'js/plugins/UI/MU_Internal/MU_Text.js', 'fonts/yuyang-W03.ttf', 'package.json', 'index.html'}
    for rel in sorted(snapshot):
        destination = BASE / 'source' / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(GAME / rel, destination)
    write_json(BASE / 'sites.json', sites)
    manifest = {'schema': 1, 'game_files': hashes,
                'snapshot_files': {rel: hashes[rel] for rel in sorted(snapshot)},
                'snapshot_scope': 'General UI, runtime parser references, and the configured Chinese font; no story corpus'}
    write_json(BASE / 'manifest.json', manifest)
    counts, per_file = collections.Counter(), {}
    script_operands = collections.Counter()
    commands, story_locations, age_locations = 0, [], []
    age = re.compile(r'未成年|未成人|幼女|小学生|中学生|幼い|(?<!\d)(?:[1-9]|1[0-7])(?:岁|歳)')
    for path in sorted((GAME / 'data').rglob('*.json')):
        obj = read_json(path)
        rel = path.relative_to(GAME).as_posix()
        local = collections.Counter()
        for pointer, value in tl.walk(obj):
            if not isinstance(value, dict) or 'code' not in value or 'parameters' not in value:
                continue
            code, params = value['code'], value['parameters']
            counts[code] += 1
            local[code] += 1
            commands += 1
            if code == 122:
                script_operands[params[3]] += 1
            if code in [101, 401, 102, 405]:
                story_locations.append({'file': rel, 'path': list(pointer), 'code': code,
                                        'decision': 'excluded_from_current_preparation',
                                        'reason': 'Narrative/choice content outside reviewed nonsexual UI scope'})
            if code == 401:
                for index, text in enumerate(params):
                    if isinstance(text, str) and age.search(text):
                        age_locations.append({'file': rel, 'path': list(pointer + ('parameters', index)),
                                              'evidence': 'Explicit minor/child-age wording; text deliberately omitted'})
        if local:
            per_file[rel] = dict(sorted(local.items()))
    rule_plugin = next(p for p in plugins if p['name'] == 'BY/BY_CommonEventLocale')
    events = read_json(GAME / 'data/CommonEvents.json')
    locale_routes = []
    for raw in json.loads(rule_plugin['parameters']['Rules']):
        rule = json.loads(raw)
        for replacement in json.loads(rule['Replacements']):
            row = json.loads(replacement)
            event_id = int(row['ReplacementEvent'])
            event = events[event_id] if event_id < len(events) else None
            lines = [c['parameters'][0] for c in event['list'] if c['code'] == 401] if event else []
            locale_routes.append({'source_event': int(rule['SourceEvent']), 'locale': row['LocaleTag'],
                                  'target_event': event_id, 'message_lines': len(lines),
                                  'source_language_lines': sum(bool(tl.CJK.search(s)) for s in lines)})
    write_json(BASE / 'reports/census.json', {
        'engine': 'RPG Maker MZ', 'engine_version': '1.9.0', 'source_language': system['locale'],
        'tracked_files': len(hashes), 'recursive_data_json_files': len(list((GAME / 'data').rglob('*.json'))),
        'event_commands': commands, 'event_codes': dict(sorted(counts.items())), 'per_file': per_file,
        'control_variable_operand_types': dict(script_operands),
        'plugins': [{'name': p['name'], 'enabled': p['status']} for p in plugins],
        'english_dictionary_entries': len(read_json(GAME / 'data/locales/en.json')),
        'english_locale_registered': False, 'locale_routes': locale_routes})
    write_json(BASE / 'reports/content_exclusions.json', {
        'scope': 'Sexual content involving minors is excluded; all narrative commands remain outside this UI preparation',
        'evidence_locations': age_locations, 'excluded_command_locations': story_locations,
        'text_reproduced': False})
    write_json(BASE / 'reports/bound_ui_fields.json', omitted_ui)
    script_inventory = []
    enabled = {'js/plugins/' + p['name'] + '.js' for p in plugins if p['status']}
    for path in sorted((GAME / 'js/plugins').rglob('*.js')):
        rel = path.relative_to(GAME).as_posix()
        literals = tl.js_parse(read_text(path))
        hits = [l for l in literals if tl.CJK.search(l['text'])]
        script_inventory.append({'file': rel, 'registered_enabled': rel in enabled,
                                 'dynamic_dependency_candidate': '/MU_Internal/' in rel,
                                 'cjk_literals': len(hits), 'parsed': True,
                                 'reviewed_sites': sum(s['file'] == rel for s in sites),
                                 'remaining_scope': 'Metadata/keys/debug and additional display literals require consumer review',
                                 'cjk_literal_locations': [{'start': l['start'], 'end': l['end'], 'line': l['line'],
                                     'hash': sha(l['text'].encode())} for l in hits]})
    write_json(BASE / 'reports/plugin_inventory.json', script_inventory)
    print(json.dumps(tl.extract(), indent=2))


if __name__ == '__main__':
    main()
