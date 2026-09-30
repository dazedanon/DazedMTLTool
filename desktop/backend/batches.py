"""Profile-wide batch index; provider operations retain the original run root."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import shutil
import uuid

from .project import atomic_json, digest

LABELS = {'refresh': 'Refresh provider status', 'cancel': 'Cancel provider batch',
          'usage': 'Fetch billed usage', 'download': 'Redownload results', 'activate': 'Prepare batch recovery',
          'bind': 'Record original batch credential', 'import': 'Import legacy batch inputs',
          'profile': 'Confirm original RPG Maker settings'}
PUBLIC = ('id', 'created_at', 'updated_at', 'status', 'api_status', 'provider', 'model', 'key_name',
          'endpoint', 'request_count', 'request_counts', 'file_set', 'cost_estimate', 'usage', 'actual_cost',
          'notes', 'workflow', 'provider_errors', 'run_id', 'sequential_token_limit', 'queued_request_count', 'local_queue')


def read_document(root, name, default=None):
    path = Path(root) / 'log' / name
    if not path.exists():
        return {} if default is None else default
    if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()) or path.stat().st_size > 256_000_000:
        raise ValueError('Batch recovery files must be regular files inside their run folder, below 256 MB.')
    result = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(result, dict):
        raise ValueError('This batch recovery file is malformed. It has been preserved.')
    return result


def entries(root):
    values = read_document(root, 'batch_history.json').get('batches', [])
    if not isinstance(values, list) or any(not isinstance(row, dict) or not isinstance(row.get('id'), str) for row in values):
        raise ValueError('This batch history is malformed. It has been preserved.')
    if len({row['id'] for row in values}) != len(values):
        raise ValueError('This batch history contains duplicate identities. It has been preserved.')
    return values


def entry_hash(row):
    return digest(json.dumps(row, sort_keys=True).encode())


def available_entries(root):
    rows = entries(root)
    state = read_document(root, 'batch_state.json')
    if state.get('status') == 'queued' and not state.get('batches') and state.get('run_id'):
        rows.append({**state, 'id': 'local-queue:' + state['run_id'], 'local_queue': True})
    return rows


def batch_root(folder, plan):
    """Resolve only a frozen, explicitly imported queue outside the profile."""
    folder = Path(folder).resolve()
    link = plan.get('batch_link')
    if not link:
        return folder
    root = Path(link['root'])
    profile = folder.parents[2]
    if (not root.is_absolute() or root.resolve(strict=True) != root or not root.is_dir()
            or root.is_relative_to(profile) or profile.is_relative_to(root)
            or (root / 'log').is_symlink() or not (root / 'log').is_dir()):
        raise ValueError('The linked original batch folder is unavailable or changed. Restore it before recovery.')
    recovery_hashes(root)  # Reject escaped paths before any shared helper writes.
    return root


def linked_queue(root, row, group):
    """Validate ownership and pin merged request content under the file lock."""
    from util import translation as translation
    state = read_document(root, 'batch_state.json')
    run_id = row.get('run_id')
    ids = {item['id'] for item in group if not item.get('local_queue')}
    active = state.get('batches') or []
    if (not run_id or state.get('run_id') != run_id or state.get('status') not in {'queued', 'partially_submitted'}
            or {item.get('id') for item in active} != ids
            or state.get('model') != row.get('model') or state.get('provider') != row.get('provider')
            or set(state.get('file_set') or []) != set(row.get('file_set') or [])):
        raise ValueError('This partial queue does not own the selected provider group. Its original files were preserved.')
    queue = translation._read_batch_queue(strict=True, queue_file=Path(root) / 'log/batch_requests.json')
    submitted = {key for member in active for key in (member.get('custom_ids') or {}).values()}
    recorded = {key for member in group for key in (member.get('custom_ids') or {}).values()}
    mappings = {member['id']: member.get('custom_ids') or {} for member in group}
    expected = state.get('queued_request_count')
    if (not queue or submitted != recorded or not submitted.issubset(queue)
            or any((member.get('custom_ids') or {}) != mappings[member['id']] for member in active)
            or expected is not None and int(expected) != len(queue)):
        raise ValueError('The original queue and paid request records do not match. Recovery was blocked.')
    for item in queue.values():
        if item.get('provider') != row.get('provider') or (item.get('params') or {}).get('model') != row.get('model'):
            raise ValueError('The queue contains a different provider or model. Recovery was blocked.')
    return {'root': str(root), 'run_id': run_id, 'digest': translation.batchQueueDigest(queue)}


def redact(value, secrets):
    if isinstance(value, dict):
        return {k: redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, '[redacted]')
    return value


def recovery_hashes(root):
    # Include the on-disk queue layout used by the shared runner, including
    # sharded requests. No provider request can follow a stale activation.
    root = Path(root)
    result = {}
    for path in sorted((root / 'log').glob('batch*')):
        paths = sorted(path.rglob('*')) if path.is_dir() else [path]
        if path.is_symlink() or any(p.is_symlink() for p in paths):
            raise ValueError('Batch recovery files cannot be symbolic links.')
        for item in paths:
            if item.is_file() and not item.name.endswith('.lock'):
                result[item.relative_to(root).as_posix()] = digest(item.read_bytes())
    return result


def recovery_profile(root, plan):
    from util.runtime_profile import is_rpgmaker_mvmz, copy_batch_runtime_profile
    if is_rpgmaker_mvmz(plan['engine']) and read_document(root, 'batch_state.json').get('runtime_profile') is None:
        profile = copy_batch_runtime_profile(plan.get('runtime_profile'))
        if profile is None:
            raise ValueError('The original RPG Maker settings are unavailable. Restore them and import the legacy run again.')
        return profile
    return None


def confirm_profile(plan):
    """Attach only the profile reviewed against this exact prepared recovery."""
    from util import translation
    root = Path(plan['source']['root'])
    plan_path = Path(plan['source']['plan_root']) / 'plan.json'
    prepared = plan['prepared']
    if plan_path.is_symlink() or digest(plan_path.read_bytes()) != prepared['plan_hash']:
        raise ValueError('The saved translation plan changed. Prepare recovery again.')
    frozen = json.loads(plan_path.read_text(encoding='utf-8'))
    if batch_root(plan_path.parent, frozen) != root:
        raise ValueError('The batch folder changed. Prepare recovery again.')
    with translation._batch_file_lock():
        if recovery_hashes(root) != prepared['hashes']:
            raise ValueError('The batch files changed after activation. Prepare recovery again.')
        profile = recovery_profile(root, frozen)
        if profile is None or profile != prepared.get('profile_confirmation'):
            raise ValueError('The original settings changed or were already confirmed. Prepare recovery again.')
        expected = read_document(root, 'batch_state.json')
    translation.saveBatchRuntimeProfile(profile, expected_state=expected)
    with translation._batch_file_lock():
        if read_document(root, 'batch_state.json') != {**expected, 'runtime_profile': profile}:
            raise ValueError('The batch changed while its profile was being saved. Prepare recovery again.')
        return {**prepared, 'hashes': recovery_hashes(root), 'profile_confirmation': None,
                'message': 'Original RPG Maker settings recorded. The saved translation can now resume.'}


class Batches:
    def __init__(self, workspace, operations, manual, *, allow_providers=False):
        self.workspace = Path(workspace)
        self.operations = operations
        self.manual = manual
        self.allow_providers = allow_providers
        self.path = self.workspace / 'batches/sources.json'
        self.external = json.loads(self.path.read_text()) if self.path.exists() else []

    def sources(self):
        values = [{'id': 'manual:' + job['id'], 'root': job.get('batch_root') or str(self.manual.folder(job['id'])),
                   'plan_root': str(self.manual.folder(job['id'])),
                   'label': job['engine'] + ' · ' + job['created'], 'job_id': job['id'], 'engine': job['engine']}
                  for job in self.manual.jobs.values() if job.get('batch_root') or any(
                      (self.manual.folder(job['id']) / 'log' / name).is_file() for name in ('batch_history.json', 'batch_state.json'))]
        evaluation = self.workspace / 'evaluation'
        if (evaluation / 'log/batch_history.json').is_file():
            values.append({'id': 'evaluation', 'root': str(evaluation), 'label': 'Translation evaluation', 'job_id': '', 'engine': ''})
        return values + self.external

    def source(self, source_id):
        source = next((value for value in self.sources() if value['id'] == source_id), None)
        if source is None:
            raise ValueError('Select an available batch run.')
        if source.get('job_id'):
            path = Path(source['plan_root']) / 'plan.json'
            if path.is_symlink() or digest(path.read_bytes()) != self.manual.jobs[source['job_id']]['plan_hash']:
                raise ValueError('The saved translation plan changed. Recovery was blocked.')
            if str(batch_root(path.parent, json.loads(path.read_text(encoding='utf-8')))) != source['root']:
                raise ValueError('The saved batch folder changed. Recovery was blocked.')
        return source

    def register(self, source):
        root = Path(source).expanduser().resolve(strict=True)
        if not root.is_dir() or root.is_relative_to(self.workspace) or self.workspace.is_relative_to(root):
            raise ValueError('Choose the original tool or run folder outside this desktop profile.')
        if not available_entries(root):
            raise ValueError('Choose the run folder containing saved batch history or an unsubmitted batch queue.')
        if not any(row['root'] == str(root) for row in self.external):
            self.external.append({'id': 'external:' + uuid.uuid4().hex, 'root': str(root), 'label': root.name, 'job_id': '', 'engine': ''})
            atomic_json(self.path, self.external)
        return self.state()

    def state(self):
        self.manual.load_saved()
        rows, errors = [], []
        sources = self.sources()
        for source in sources:
            try:
                if not Path(source['root']).is_dir():
                    raise ValueError('Restore this original run folder before recovery.')
                for row in available_entries(source['root']):
                    public = {key: row.get(key) for key in PUBLIC}
                    if row.get('key_name') in source.get('credential_conflicts', []):
                        public.update(key_name='', notes='This credential name conflicts with an existing desktop credential. Select the imported Qt credential before recovery.')
                    rows.append({**public, 'source_id': source['id'], 'revision': entry_hash(row)})
            except (OSError, ValueError) as exc:
                errors.append({'source_id': source['id'], 'message': str(exc)})
        rows.sort(key=lambda row: row.get('created_at') or '', reverse=True)
        from .settings import SettingsStore
        from util.api_keys import load_vault
        from util.translation_task import TRANSLATION_MODULE_SPECS
        vault = load_vault(SettingsStore(self.workspace).vault_path)
        return redact({'sources': sources, 'rows': rows, 'errors': errors, 'allow_providers': self.allow_providers,
                'credentials': list(vault['keys']),
                'engines': [spec[0] for spec in TRANSLATION_MODULE_SPECS],
                'active': self.operations.active or None,
                'jobs': sorted((j for j in self.operations.jobs.values() if j.get('project_id', '').startswith('batch:')),
                               key=lambda job: job['created'], reverse=True)[:30]}, [r['secret'] for r in vault['keys'].values()])

    def action(self, source_id, batch_id, action, *, key_name='', revision='', engine='', prepared_id=''):
        source = self.source(source_id)
        row = next((r for r in available_entries(source['root']) if r['id'] == batch_id), None)
        if row is None or action not in LABELS:
            raise ValueError('Select a saved batch and a supported action.')
        conflicted = row.get('key_name') in source.get('credential_conflicts', [])
        if conflicted and action != 'bind':
            raise ValueError('Confirm the imported Qt credential for this batch before recovery.')
        if not self.allow_providers and action not in {'bind', 'import', 'profile'}:
            raise ValueError('Provider operations are disabled in this session. Local history remains available.')
        if row.get('local_queue') and action not in {'bind', 'import', 'activate', 'profile'}:
            raise ValueError('This queue has no provider job yet. Import its inputs and prepare recovery first.')
        if row.get('workflow') == 'evaluation' and action in {'download', 'activate', 'usage', 'import'}:
            raise ValueError('Open this run in Translation evaluation to collect its results.')
        if action == 'activate' and not source['job_id']:
            raise ValueError('Import this legacy run into a manual recovery workspace before consuming results.')
        if action == 'activate':
            original = self.manual.jobs[source['job_id']]
            plan_path = Path(source['plan_root']) / 'plan.json'
            if plan_path.is_symlink() or digest(plan_path.read_bytes()) != original['plan_hash']:
                raise ValueError('The saved translation plan changed. Recovery was blocked.')
        if action == 'import':
            from util.translation_task import translation_module
            translation_module(engine)
            if source['job_id']:
                raise ValueError('This batch already has a saved manual workspace.')
        # Named credentials are mandatory at this boundary. Never silently use
        # the current UI credential for an old provider job.
        key = key_name if action == 'bind' else row.get('key_name')
        if action == 'bind' and (row.get('key_name') and not conflicted or revision != entry_hash(row)):
            raise ValueError('The history entry already has a credential or changed. Reload before recording its original credential.')
        if not key:
            raise ValueError('This legacy batch has no saved credential name. Bind its original credential before contacting the provider.')
        from .settings import SettingsStore
        from util.api_keys import load_vault
        vault = load_vault(SettingsStore(self.workspace).vault_path)['keys']
        if key not in vault:
            raise ValueError(f'Saved credential {key!r} is unavailable. Import it in Settings first.')
        if conflicted:
            original = source.get('credential_aliases', {}).get(row['key_name'])
            if not original or original not in vault or vault[key] != vault[original]:
                raise ValueError('Select the imported Qt credential that originally submitted this batch.')
        plan = {'kind': 'batch', 'project_id': 'batch:' + source_id, 'action': action, 'label': LABELS[action],
                'workspace': str(self.workspace), 'source': source, 'batch_id': batch_id,
                'entry_hash': entry_hash(row), 'key_name': key, 'engine': engine}
        if conflicted:
            plan['rebind_from'] = row['key_name']
        if action == 'profile':
            prepared = self.prepared(prepared_id)
            if (prepared['job_id'] != source.get('job_id') or prepared.get('batch_id') != batch_id
                    or not prepared.get('profile_confirmation')):
                raise ValueError('Prepare this legacy batch and review its original settings first.')
            plan['prepared'] = prepared
        return self.operations.start(plan)

    def prepared(self, operation_id):
        job = self.operations.jobs.get(operation_id)
        if not job or job.get('action') not in {'activate', 'profile'} or job['status'] != 'complete':
            raise ValueError('Prepare this batch for recovery first.')
        result = job.get('result') or {}
        identity = result.get('job_id', '')
        folder = self.manual.folder(identity)
        saved_plan = json.loads((folder / 'plan.json').read_text(encoding='utf-8'))
        if recovery_hashes(batch_root(folder, saved_plan)) != result.get('hashes'):
            raise ValueError('The batch files changed after activation. Prepare recovery again.')
        plan_path = folder / 'plan.json'
        if plan_path.is_symlink() or digest(plan_path.read_bytes()) != result.get('plan_hash'):
            raise ValueError('The saved translation plan changed. Recovery was blocked.')
        return result

    def resume(self, operation_id):
        result = self.prepared(operation_id)
        folder = self.manual.folder(result['job_id'])
        plan = json.loads((folder / 'plan.json').read_text(encoding='utf-8'))
        if recovery_profile(batch_root(folder, plan), plan) is not None:
            raise ValueError('Review and confirm the original RPG Maker settings before resuming this legacy batch.')
        return self.manual.resume_batch(result['job_id'], result)


def run_action(plan, log):
    root = Path(plan['source']['root']).resolve(strict=True)
    row = next((r for r in available_entries(root) if r['id'] == plan['batch_id']), None)
    if row is None or entry_hash(row) != plan['entry_hash']:
        raise ValueError('The selected history entry changed. Refresh before trying again.')
    os.chdir(root)  # Only this dedicated child process owns this cwd.
    os.environ.update(PYTHON_DOTENV_DISABLED='1', TIKTOKEN_CACHE_DIR=str(Path(__file__).resolve().parents[2] / 'data/tokenizers'))
    if os.getenv('DAZEDTL_TEST_OFFLINE') == '1' or plan['action'] in {'bind', 'import', 'profile'}:
        import socket
        def blocked(*args, **kwargs):
            raise RuntimeError('Network access is disabled for this local operation.')
        socket.create_connection = socket.socket.connect = socket.socket.connect_ex = blocked
    from .settings import SettingsStore
    from util import api_keys
    api_keys.API_KEYS_PATH = SettingsStore(Path(plan['workspace'])).vault_path
    secrets = [item['secret'] for item in api_keys.load_vault()['keys'].values() if item['secret']]
    key_name = plan['key_name']
    secret = api_keys.get_secret(key_name) or ''
    if not secret and not api_keys.is_keyless(key_name):
        raise ValueError('The original credential is no longer available.')
    endpoint = row.get('endpoint') or api_keys.get_endpoint(key_name) or ''
    os.environ.update(key=secret or 'not-needed', api=endpoint, model=row.get('model') or '',
                      API_PROVIDER=row.get('provider') or 'anthropic', API_KEY_OPTIONAL=str(api_keys.is_keyless(key_name)).lower())
    def clean(value):
        return redact(value, secrets)
    streams = sys.stdout, sys.stderr
    class RedactedStream:
        def __init__(self, stream): self.stream = stream
        def write(self, value): return self.stream.write(clean(value))
        def flush(self): return self.stream.flush()
        def isatty(self): return False
    sys.stdout, sys.stderr = (RedactedStream(stream) for stream in streams)
    try:
        from util import batch_history as history
        action, identity = plan['action'], plan['batch_id']
        if action == 'profile':
            return confirm_profile(plan)
        if action == 'import':
            return import_run(plan, row, log)
        if action == 'bind':
            with history._batch_file_lock():
                if row.get('local_queue'):
                    current = next((r for r in available_entries(root) if r['id'] == identity), None)
                    if current is None or (current.get('key_name') or '') != (plan.get('rebind_from') or '') or entry_hash(current) != plan['entry_hash']:
                        raise ValueError('This queue changed before its credential could be recorded.')
                    state = read_document(root, 'batch_state.json')
                    state.update(key_name=key_name, endpoint=endpoint)
                    atomic_json(root / 'log/batch_state.json', state)
                    return {'message': 'Original credential recorded. No provider request was made.'}
                document = history._read_history_unlocked()
                current = next(r for r in document['batches'] if r['id'] == identity)
                if (current.get('key_name') or '') != (plan.get('rebind_from') or '') or entry_hash(current) != plan['entry_hash']:
                    raise ValueError('This history entry changed before its credential could be recorded.')
                current.update(key_name=key_name, endpoint=endpoint)
                history._write_history_unlocked(document)
            return {'message': 'Original credential recorded. No provider request was made.'}
        if plan['source'].get('credential_conflicts'):
            for member in history._translation_group_entries({'batches': entries(root)}, row):
                if member.get('key_name') in plan['source']['credential_conflicts']:
                    raise ValueError('Confirm the imported Qt credentials for every batch in this group before contacting its provider.')
        # Shared recovery may include every provider split in this group.
        # Validate their credentials before any split can make a request.
        if action in {'download', 'activate'} and not row.get('local_queue'):
            for member in history._translation_group_entries({'batches': entries(root)}, row):
                name = member.get('key_name')
                if not name or not (api_keys.get_secret(name) or api_keys.is_keyless(name)):
                    raise ValueError('Every batch in this group needs its original named credential before recovery.')
        log(LABELS[action] + ': ' + identity)
        if action == 'refresh':
            result = history.refresh_batch_status(identity)
            return {'entry': clean({key: result.get(key) for key in PUBLIC})}
        if action == 'cancel':
            rows = history.cancel_batches([identity])
            return clean({'ok': all(r.get('ok') for r in rows), 'results': rows,
                          'message': 'Cancellation requested. Refresh status to check completion.' if all(r.get('ok') for r in rows) else rows[0].get('error', 'Cancellation failed.')})
        if action == 'usage':
            result = history.usage_for_batch(identity)
            return clean({key: result.get(key) for key in ('usage', 'actual_cost', 'succeeded', 'errored', 'model')})
        if action == 'download':
            result = history.redownload_batch(identity)
            return clean(result)
        if action == 'activate':
            plan_root = Path(plan['source'].get('plan_root') or root)
            original = json.loads((plan_root / 'plan.json').read_text(encoding='utf-8'))
            if batch_root(plan_root, original) != root:
                raise ValueError('The original batch folder changed. Recovery was blocked.')
            if original['mode'] != 'batch':
                raise ValueError('This saved run is not a batch translation.')
            if original.get('batch_link') and row.get('run_id') != original['batch_link']['run_id']:
                raise ValueError('This provider group does not belong to the linked translation run.')
            for member in history._translation_group_entries({'batches': entries(root)}, row):
                if (member.get('key_name') != original['key_name']
                    or member.get('model') and member['model'] != original['settings']['model']
                    or member.get('endpoint') and member['endpoint'] != original['settings']['api']
                    or member.get('file_set') and set(member['file_set']) != set(original['selected'])):
                    raise ValueError('This provider group does not match the saved credential, model, endpoint or file set of its translation plan.')
            state = None
            with history._batch_file_lock():
                active = read_document(root, 'batch_state.json')
                if active.get('status') in {'queued', 'partially_submitted'}:
                    link = linked_queue(root, row, history._translation_group_entries({'batches': entries(root)}, row))
                    if original.get('batch_link') and link != original['batch_link']:
                        raise ValueError('The linked queue changed since import. Import its inputs again before recovery.')
                    state = active['status']
            if state is None:
                state = history.activate_for_resume(identity)
            return {'state': state, 'hashes': recovery_hashes(root), 'job_id': plan['source']['job_id'], 'batch_id': identity,
                    'plan_hash': digest((plan_root / 'plan.json').read_bytes()),
                    'profile_confirmation': recovery_profile(root, original),
                    'message': 'Recovery is ready. Review the next step before resuming the saved engine.'}
        raise ValueError('Unsupported batch action.')
    except Exception as exc:
        # Provider exceptions sometimes contain request headers. They must not
        # reach the action log or renderer with the stored secret intact.
        raise ValueError(clean(str(exc))) from None
    finally:
        sys.stdout, sys.stderr = streams


def import_run(plan, row, log):
    """Copy inputs; keep unsubmitted requests under the original shared lock."""
    import threading
    from .manual import ManualJobs
    from .settings import SettingsStore, FIELDS, validate_values
    from util.engine_options import engine_options, validate_engine_options
    from util.batch_history import _batch_file_lock, _translation_group_entries
    from dotenv import dotenv_values
    root = Path(plan['source']['root'])
    workspace = Path(plan['workspace'])
    engine = plan['engine']
    with _batch_file_lock():
        state = read_document(root, 'batch_state.json')
        group = _translation_group_entries({'batches': entries(root)}, row)
        link = linked_queue(root, row, group) if state.get('status') in {'queued', 'partially_submitted'} else None
    if not link and any(member.get('sequential_token_limit') for member in group):
        submitted = len({key for member in group for key in (member.get('custom_ids') or {}).values()})
        expected = max(int(member.get('queued_request_count') or 0) for member in group)
        if submitted != expected:
            raise ValueError('The original sequential run still has unsubmitted requests. Finish its original queue before importing.')
    files = row.get('file_set')
    if not isinstance(files, list) or not files:
        raise ValueError('This legacy batch has no recorded file set. Restore its original run metadata before importing.')
    settings = SettingsStore(workspace)
    config = settings.describe()
    # Preserve local, nonsecret legacy options when an original installation
    # is available. Provider identity always comes from its durable batch row.
    env_path = root / '.env'
    if env_path.is_file():
        if env_path.is_symlink() or env_path.stat().st_size > 1_000_000:
            raise ValueError('Legacy settings must be a regular file below 1 MB.')
        env = dotenv_values(env_path, interpolate=False)
        for field in FIELDS:
            key, kind = field['key'], field['type']
            if key not in env or env[key] is None:
                continue
            value = env[key]
            config['values'][key] = value.casefold() in {'true', '1', 'yes'} if kind == 'boolean' else int(value) if kind == 'integer' else float(value) if kind == 'number' else value
    if plan['source'].get('legacy_engine_options'):
        config['engines'] = validate_engine_options(plan['source']['legacy_engine_options'])
    elif (root / 'modules').is_dir():
        config['engines'] = validate_engine_options({name: {f['key']: f['default'] for f in schema['fields']}
                                                   for name, schema in engine_options(root).items()})
    config['active_key'] = row['key_name']
    config['values'].update(model=row['model'], API_PROVIDER=row.get('provider') or 'anthropic')
    route = row.get('endpoint') or settings.runtime(config['values'], row['key_name'])['api']
    config['values']['api'] = route
    config['values'] = validate_values(config['values'])
    # The new plan must not silently route through a credential that was
    # edited to a different host since submission.
    if settings.runtime(config['values'], row['key_name'])['api'] != route:
        raise ValueError('Restore this credential’s original endpoint in Settings before importing its run.')
    manual = ManualJobs(workspace, threading.RLock(), allow_providers=True)
    if link:
        for saved in manual.jobs.values():
            if saved.get('batch_root') == str(root):
                frozen = json.loads((manual.folder(saved['id']) / 'plan.json').read_text(encoding='utf-8'))
                if (frozen.get('batch_link') == link and frozen['engine'] == engine
                        and frozen['engines'] == config['engines'] and frozen['settings'] == config['values']):
                    return {'message': 'This queue already has a linked manual workspace. Prepare recovery there.',
                            'job_id': saved['id'], 'source_id': 'manual:' + saved['id'], 'batch_id': row['id']}
    inventory = manual.inspect(str(root / 'files'), engine)
    log('Copying the recorded inputs into an isolated manual workspace.' + (' The queue remains in its original folder.' if link else ' Recovery data will also be copied.'))
    job = manual.start(inventory['source'], engine, files, inventory['revision'], 'batch', str(root), configuration=config, launch=False)
    target = manual.folder(job['id'])
    try:
        with _batch_file_lock():
            if entry_hash(next(r for r in available_entries(root) if r['id'] == row['id'])) != plan['entry_hash']:
                raise ValueError('The original batch changed while import was being prepared.')
            before = recovery_hashes(root)
            current_state = read_document(root, 'batch_state.json')
            if link:
                if linked_queue(root, row, group) != link:
                    raise ValueError('The original queue changed while import was being prepared.')
            elif current_state.get('status') in {'queued', 'partially_submitted'}:
                raise ValueError('A new queue appeared in the original run. Import was stopped.')
            else:
                for name in before:
                    destination = target / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(root / name, destination)
                if recovery_hashes(root) != before or recovery_hashes(target) != before:
                    raise ValueError('Original recovery files changed during import. Retry after the original tool is idle.')
        frozen = json.loads((target / 'plan.json').read_text())
        if row.get('runtime_profile'):
            frozen['runtime_profile'] = row['runtime_profile']
        for item in inventory['files']:
            original = root / 'files' / item['name']
            if original.is_symlink() or not original.resolve().is_relative_to(root / 'files') or digest(original.read_bytes()) != item['sha256']:
                raise ValueError('An original engine input changed during import.')
            for directory in ('inputs', 'files'):
                destination = target / directory / item['name']
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, destination)
                if digest(destination.read_bytes()) != item['sha256']:
                    raise ValueError('An original engine input changed during import.')
        for relative, destination in [('skills/system.md', 'system.md'), ('data/skills/system.md', 'system.md'), ('data/glossary_base.txt', 'base-glossary.txt'),
                                      ('data/translation_contexts.json', 'translation_contexts.json'), ('data/sfx_reference/j_ono.json', 'sfx.json')]:
            original = root / relative
            if original.is_file():
                if original.is_symlink() or not original.resolve().is_relative_to(root) or original.stat().st_size > 10_000_000:
                    raise ValueError('Legacy prompt and reference files must be regular files inside the original folder, below 10 MB.')
                shutil.copyfile(original, target / 'context' / destination)
        frozen['context_hashes'] = {p.relative_to(target).as_posix(): digest(p.read_bytes())
                                    for folder in ('context', 'game') for p in (target / folder).rglob('*') if p.is_file()}
        frozen['legacy_origin'] = {'root': str(root), 'batch_id': row['id']}
        if link:
            frozen['batch_link'] = link
            manual.jobs[job['id']]['batch_root'] = str(root)
            # Older builds must refuse this job, rather than ignoring the
            # queue link and re-collecting fresh paid work after a rollback.
            manual.jobs[job['id']]['version'] = 2
        atomic_json(target / 'plan.json', frozen)
        atomic_json(target / 'prepared.json', {'ready': True})
        manual.jobs[job['id']]['plan_hash'] = digest((target / 'plan.json').read_bytes())
        manual.save(manual.jobs[job['id']])
        return {'message': ('Legacy inputs imported; the queue remains linked to its original folder, which must stay available. '
                            if link else 'Legacy inputs and recovery data imported. ')
                           + 'Select the new manual run in Batch history and prepare recovery.',
                'job_id': job['id'], 'source_id': 'manual:' + job['id'], 'batch_id': row['id']}
    except Exception:
        shutil.rmtree(target)
        raise
