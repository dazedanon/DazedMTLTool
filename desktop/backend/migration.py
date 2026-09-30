"""Journaled, local-only migration from an existing Qt installation."""
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import sys
import tempfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from desktop.bootstrap import ENGINE_FILES, archive_path, atomic_json, digest, regular_folder

RECENT_KEYS = {'workflow/last_game_folder': 'workflow', 'wolf_workflow/last_game_folder': 'workflow',
               'len_method/game_root': 'len', 'last_open_dir': 'manual', 'last_game_folder': 'workflow'}


def read_qt_preferences():
    """Read only the old app's string preferences; Qt is not needed."""
    if os.getenv('DAZEDTL_NO_LEGACY_OS_SETTINGS') == '1':
        return {}
    values = {}
    if os.name == 'nt':
        import winreg
        for application in ('DazedMTLTool', 'DazedTL'):
            for key in RECENT_KEYS:
                group, _, name = key.rpartition('/')
                subkey = 'Software\\DazedTranslations\\' + application + ('\\' + group if group else '')
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as registry:
                        value, kind = winreg.QueryValueEx(registry, name)
                        if kind in {winreg.REG_SZ, winreg.REG_EXPAND_SZ}:
                            values[key] = value
                except OSError:
                    pass
    elif sys.platform == 'darwin':
        for application in ('DazedMTLTool', 'DazedTL'):
            for file in (Path.home() / 'Library/Preferences').glob('*DazedTranslations*' + application + '*.plist'):
                if file.is_file() and not file.is_symlink() and file.stat().st_size < 2_000_000:
                    with file.open('rb') as stream:
                        values.update({k: v for k, v in plistlib.load(stream).items() if k in RECENT_KEYS and isinstance(v, str)})
    else:
        base = Path(os.getenv('XDG_CONFIG_HOME', Path.home() / '.config')) / 'DazedTranslations'
        for application in ('DazedMTLTool', 'DazedTL'):
            file = base / (application + '.conf')
            if not file.is_file() or file.is_symlink() or file.stat().st_size > 2_000_000:
                continue
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            parser.optionxform = str
            parser.read(file, encoding='utf-8')
            for section in parser.sections():
                for name, value in parser.items(section):
                    key = name if section == 'General' else section + '/' + name
                    if key in RECENT_KEYS and not value.startswith('@'):
                        values[key] = value.strip('"').replace('\\\\', '\\').replace('\\"', '"')
    return values


def read_private(file, maximum=2_000_000):
    if file.is_symlink() or not file.is_file() or file.stat().st_size > maximum:
        raise ValueError(f'The previous {file.name} must be a regular file below {maximum // 1_000_000} MB.')
    return file.read_bytes()


def identity(source):
    return hashlib.sha256(os.path.normcase(str(source.resolve())).encode()).hexdigest()[:16]


def capture(source, workspace, *, preferences=None):
    """Capture embedded engine settings before the launcher refreshes code."""
    from dotenv import dotenv_values
    from util.engine_options import engine_options
    source, workspace = Path(source).resolve(), Path(workspace).resolve()
    backup = regular_folder(workspace / 'migrations' / ('qt-' + identity(source)))
    marker = backup / 'snapshot.json'
    if marker.is_file():
        snapshot = json.loads(marker.read_text())
        receipt = backup / 'migration.json'
        if receipt.is_file() and json.loads(receipt.read_text()).get('status') == 'complete':
            return snapshot
        # Retry interrupted migrations with the latest credentials/preferences,
        # retaining each prior original and the pre-upgrade engine options.
        for relative in ('.env', 'data/api_keys.json'):
            original = source / relative
            raw = read_private(original) if original.exists() else None
            current_hash = hashlib.sha256(raw).hexdigest() if raw is not None else None
            if current_hash == snapshot['source_hashes'].get(relative):
                continue
            target = backup / 'original' / relative
            if target.exists():
                history = backup / 'history' / (relative.replace('/', '-') + '-' + digest(target))
                history.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, history)
            if raw is None:
                target.unlink(missing_ok=True)
                snapshot['source_hashes'].pop(relative, None)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                target.chmod(0o600)
                snapshot['source_hashes'][relative] = current_hash
                snapshot['legacy'] = True
        snapshot['env'] = dict(dotenv_values(backup / 'original/.env', interpolate=False)) if (backup / 'original/.env').exists() else {}
        atomic_json(marker, snapshot)
        return snapshot
    legacy = (source / '.env').is_file() or (source / 'data/api_keys.json').is_file() or (source / 'data/last_update_sha.txt').is_file() or any(
        (source / 'log' / name).exists() for name in ('batch_history.json', 'batch_state.json', 'evaluations', 'evaluation_work'))
    snapshot = {'version': 1, 'source': str(source), 'backup': str(backup), 'legacy': legacy,
                'source_hashes': {}, 'env': {}, 'engines': {}, 'preferences': {}, 'warnings': []}
    if legacy:
        for relative in ['.env', 'data/api_keys.json', *('modules/' + name for name in ENGINE_FILES)]:
            original = source / relative
            if not original.exists():
                continue
            raw = read_private(original)
            target = backup / 'original' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            target.chmod(0o600)
            snapshot['source_hashes'][relative] = hashlib.sha256(raw).hexdigest()
        if (backup / 'original/.env').exists():
            snapshot['env'] = dict(dotenv_values(backup / 'original/.env', interpolate=False))
        try:
            snapshot['engines'] = {engine: {field['key']: field['default'] for field in schema['fields']}
                                   for engine, schema in engine_options(source).items()}
        except (OSError, SyntaxError, ValueError):
            snapshot['warnings'].append('Some old engine preferences could not be read. Their original source files are backed up.')
        snapshot['preferences'] = preferences if preferences is not None else read_qt_preferences()
    atomic_json(marker, snapshot)
    return snapshot


def import_preferences(snapshot, workspace, code_root, journal):
    from desktop.backend.settings import SettingsStore, FIELDS, validate_values
    from util import api_keys
    from util.engine_options import engine_options, validate_engine_options
    store = SettingsStore(workspace, code_root=code_root)
    saved = store.read()
    values = dict(saved['values'])
    engines = {engine: dict(fields) for engine, fields in saved['engines'].items()}
    if snapshot['legacy']:
        existing_values = set(values) if saved['revision'] else set()
        existing_engines = {engine: set(fields) for engine, fields in engines.items()} if saved['revision'] else {}
        env = snapshot['env']
        if 'org' in env and 'organization' not in env:
            env = {**env, 'organization': env['org']}
        if env.get('mistralReqPerMin') and not env.get('mistralReqPerSec'):
            try:
                env = {**env, 'mistralReqPerSec': str(max(0.05, float(env['mistralReqPerMin']) / 60))}
            except (TypeError, ValueError):
                journal['warnings'].append('The old Mistral request-rate setting needs review; its value is backed up.')
        for field in FIELDS:
            key, kind = field['key'], field['type']
            if key in existing_values:
                continue
            raw = env.get(key)
            if raw is None:
                continue
            try:
                value = raw.casefold() in {'true', '1', 'yes'} if kind == 'boolean' else int(raw) if kind == 'integer' else float(raw) if kind == 'number' else raw
                values = validate_values({**values, key: value})
            except (TypeError, ValueError):
                journal['warnings'].append(f'The old {field["label"]} was invalid; its original value is in the backup.')
        schemas = engine_options(code_root)
        for engine, old_values in snapshot['engines'].items():
            fields = {field['key']: field for field in schemas.get(engine, {}).get('fields', [])}
            for key, value in old_values.items():
                if key not in fields or key in existing_engines.get(engine, set()):
                    continue
                if fields[key]['type'] == 'choices':
                    value = [item for item in value if item in fields[key]['choices']]
                try:
                    normalized = validate_engine_options({engine: {key: value}}, code_root)
                    engines.setdefault(engine, {}).update(normalized[engine])
                except (TypeError, ValueError):
                    journal['warnings'].append(f'The old {engine}/{key} needs review; its original value is in the backup.')
        if saved['revision'] == 0:
            store.save(saved['revision'], values, engines)
            journal['settings_imported'] = True
        else:
            journal['existing_desktop_settings_kept'] = True
            if values != saved['values'] or engines != saved['engines']:
                # Preserve an existing unsaved draft for explicit review.
                atomic_json(store.path, {**saved, 'revision': saved['revision'] + 1,
                                        'values': validate_values(values), 'engines': validate_engine_options(engines, code_root)})
    vault = api_keys.load_vault(store.vault_path)
    imported = api_keys.load_vault(Path(snapshot['backup']) / 'original/data/api_keys.json')
    if not imported['keys'] and snapshot['env'].get('key') and not snapshot['env']['key'].startswith('<'):
        imported = {'active': 'Imported', 'keys': {'Imported': {'secret': snapshot['env']['key'], 'endpoint': snapshot['env'].get('api') or '', 'keyless': False}}}
    aliases, conflicts = {}, []
    for name, entry in imported['keys'].items():
        selected = name
        if selected in vault['keys'] and vault['keys'][selected] != entry:
            selected = name[:72] + ' (Qt ' + identity(Path(snapshot['source']))[:8] + ')'
            conflicts.append(name)
            journal['warnings'].append(f'Credential “{name}” already exists with different details. The Qt credential was kept as “{selected}”; choose it before recovering that old batch.')
        if selected not in vault['keys']:
            vault['keys'][selected] = entry
        aliases[name] = selected
    vault['active'] = vault['active'] or aliases.get(imported['active'], '')
    api_keys.save_vault(vault, store.vault_path)
    journal.update(credentials_imported=len(imported['keys']), credential_conflicts=conflicts, credential_aliases=aliases)


def import_shared_instructions(source, workspace, journal):
    defaults = json.loads((source / 'desktop/engine-defaults/manifest.json').read_text()).get('shared_data', {})
    for name, shipped_hash in defaults.items():
        relative = archive_path(name)
        original = source / 'data' / relative
        if not original.is_file() or digest(original) == shipped_hash:
            continue
        destination = workspace / 'shared-data' / relative
        if destination.exists():
            continue
        text = read_private(original, 1_000_000).decode('utf-8-sig')
        # Existing customized templates are retained verbatim. Their validation
        # runs in the instruction editor before a later explicit save.
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding='utf-8')
        journal['instructions_imported'] += 1


def register_batches(source, workspace, journal, snapshot):
    if not any((source / 'log' / name).exists() for name in ('batch_history.json', 'batch_state.json', 'batch_queue.json', 'batch_queue')):
        return
    from desktop.backend.batches import available_entries
    if not available_entries(source):
        return
    target = workspace / 'batches/sources.json'
    values = json.loads(target.read_text()) if target.is_file() else []
    row = next((row for row in values if row['root'] == str(source)), None)
    if row is None:
        row = {'id': 'external:qt-' + identity(source), 'root': str(source),
               'label': 'Previous installation · ' + source.name, 'job_id': '', 'engine': ''}
        values.append(row)
    row['credential_conflicts'] = journal['credential_conflicts']
    row['credential_aliases'] = journal['credential_aliases']
    row['legacy_engine_options'] = snapshot['engines']
    atomic_json(target, values)
    journal['batch_history_linked'] = True


def import_evaluations(source, workspace, journal, receipt):
    if not any((source / 'log' / name).is_dir() for name in ('evaluations', 'evaluation_work')):
        return
    from util import evaluation
    project = regular_folder(workspace / 'evaluation')
    for storage in ('evaluation_work', 'evaluations'):
        folder = source / 'log' / storage
        if not folder.is_dir() or folder.is_symlink():
            continue
        for previous in sorted(folder.iterdir()):
            if not previous.is_dir() or previous.is_symlink() or not (previous / 'state.json').is_file():
                continue
            key = str(previous)
            if key in journal['evaluations_imported']:
                continue
            try:
                if any(file.is_symlink() for file in previous.rglob('*')):
                    raise ValueError('A saved evaluation contains links.')
                before = digest(previous / 'state.json')
                previous_state = json.loads((previous / 'state.json').read_text())
                previous_manifest = digest(previous / 'manifest.json')
                # A process may stop after import's atomic rename but before
                # the migration receipt. Reuse that exact imported run.
                recovered = None
                for state_file in project.glob('log/evaluation*/*/state.json'):
                    saved = json.loads(state_file.read_text())
                    if (saved.get('imported_from_run_id') == previous_state.get('run_id')
                            and (state_file.parent / 'manifest.json').is_file()
                            and digest(state_file.parent / 'manifest.json') == previous_manifest):
                        recovered = state_file.parent
                        break
                if recovered is not None:
                    journal['evaluations_imported'][key] = str(recovered)
                    atomic_json(receipt, journal)
                    continue
                with tempfile.TemporaryDirectory(prefix='qt-import-', dir=Path(journal['backup'])) as temporary:
                    archive = evaluation.export_run_archive(previous, Path(temporary) / 'run.dazedeval')
                    if digest(previous / 'state.json') != before:
                        raise ValueError('The old evaluation is still changing.')
                    imported = evaluation.import_run_archive(project, archive)
                journal['evaluations_imported'][key] = str(imported)
                atomic_json(receipt, journal)
            except (OSError, ValueError, KeyError):
                journal['warnings'].append(f'Evaluation {previous.name} remains in the original installation. Import it from Evaluation → Archives after the old app is closed.')


def apply(source, workspace):
    source, workspace = Path(source).resolve(), Path(workspace).resolve()
    snapshot = capture(source, workspace)
    receipt = Path(snapshot['backup']) / 'migration.json'
    journal = json.loads(receipt.read_text()) if receipt.is_file() else {
        'version': 1, 'source': str(source), 'backup': snapshot['backup'], 'status': 'pending',
        'settings_imported': False, 'credentials_imported': 0, 'credential_conflicts': [],
        'instructions_imported': 0, 'evaluations_imported': {}, 'warnings': list(snapshot['warnings'])}
    if journal['status'] == 'complete':
        return journal
    if snapshot['legacy']:
        for name in ('.env', 'data/api_keys.json'):
            if name in snapshot['source_hashes'] and digest(source / name) != snapshot['source_hashes'][name]:
                raise ValueError('The old app changed its settings during migration. Close it before continuing; the captured originals are backed up.')
        import_preferences(snapshot, workspace, source, journal)
        atomic_json(receipt, journal)
        import_shared_instructions(source, workspace, journal)
        register_batches(source, workspace, journal, snapshot)
        import_evaluations(source, workspace, journal, receipt)
    recent = []
    for key, page in RECENT_KEYS.items():
        value = snapshot['preferences'].get(key, '')
        if value and isinstance(value, str):
            path = Path(value).expanduser()
            if path.is_absolute() and path.is_dir() and not any(row['source'] == str(path) for row in recent):
                recent.append({'source': str(path), 'page': page, 'name': path.name})
    journal.update(status='complete', recent=recent)
    atomic_json(receipt, journal)
    if snapshot['legacy']:
        atomic_json(workspace / 'legacy-upgrade.json', {
            'version': 1, 'source': str(source), 'report': str(receipt), 'recent': recent,
            'settings_imported': journal['settings_imported'], 'credentials_imported': journal['credentials_imported'],
            'evaluations_imported': len(journal['evaluations_imported']), 'batch_history_linked': journal.get('batch_history_linked', False),
            'warnings': journal['warnings'],
            'preserved_folders': [str(source / name) for name in ('files', 'translated', 'log') if (source / name).is_dir()],
        })
    return journal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--capture', action='store_true')
    args = parser.parse_args()
    # Migration never contacts a provider, even if a parent shell has keys.
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    os.environ['DAZEDTL_TEST_OFFLINE'] = '1'
    result = capture(args.source, args.workspace) if args.capture else apply(args.source, args.workspace)
    print(json.dumps({'backup': result['backup'], 'status': result.get('status', 'captured')}))


if __name__ == '__main__':
    main()
