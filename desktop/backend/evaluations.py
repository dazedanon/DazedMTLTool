"""Desktop evaluation orchestration; all evaluation semantics live in util.evaluation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

from .project import atomic_json, digest
from .batches import redact

LABELS = {
    'catalog': 'Load evaluation history', 'scan': 'Inspect evaluation content',
    'prepare': 'Prepare evaluation', 'open': 'Read evaluation results',
    'estimate': 'Review submission costs', 'submit': 'Run evaluation',
    'refresh': 'Collect evaluation results', 'bind': 'Bind imported credentials',
    'review_preview': 'Preview blind review', 'review_export': 'Export blind review',
    'review_import': 'Import reviewed CSV', 'calibration': 'Load human calibration',
    'archive_export': 'Export evaluation archive', 'archive_import': 'Import evaluation archive',
    'legacy_import': 'Import legacy evaluation', 'skill': 'Prepare review instructions',
    'models': 'Discover evaluation models',
}


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    if path.is_symlink() or path.stat().st_size > 256_000_000:
        raise ValueError('Evaluation files must be regular files below 256 MB.')
    return json.loads(path.read_text(encoding='utf-8'))


def run_path(project, identity):
    if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9._-]+', identity) or identity in {'.', '..'}:
        raise ValueError('Select a saved evaluation.')
    for storage in ('evaluation_work', 'evaluations'):
        path = Path(project) / 'log' / storage / identity
        if path.is_dir() and not path.is_symlink() and path.resolve().is_relative_to(Path(project).resolve()):
            return path
    raise ValueError('This evaluation is no longer available. Reload history.')


def revision(path):
    # Cover result/checkpoint files as well as settings. Review exports and
    # provider continuation cannot use an old preview after any run mutation.
    rows = {}
    for item in sorted(Path(path).rglob('*')):
        if item.is_symlink():
            raise ValueError('Evaluation runs cannot contain symbolic links.')
        if item.is_file() and item.suffix != '.lock':
            rows[item.relative_to(path).as_posix()] = digest(item.read_bytes())
    return digest(json.dumps(rows, sort_keys=True).encode())


def vault_for(workspace):
    from .settings import SettingsStore
    from util.api_keys import load_vault
    return load_vault(SettingsStore(workspace).vault_path)


def credential_signature(vault):
    # Store only a digest in plans; replacing a named key invalidates consent.
    return digest(json.dumps(vault['keys'], sort_keys=True).encode())


class Evaluations:
    def __init__(self, workspace, operations, *, allow_providers=False):
        self.workspace = Path(workspace)
        self.root = self.workspace / 'evaluation'
        self.operations = operations
        self.allow_providers = allow_providers

    def state(self, run_id='', query='', selection='all', page=0, review_mode='paired'):
        cache = read_json(self.root / 'desktop-index.json', {})
        view = read_json(self.root / 'views' / (run_id + '.json'), {}) if re.fullmatch(r'[A-Za-z0-9._-]+', run_id) and run_id not in {'.', '..'} else {}
        if view:
            samples = view.pop('samples', [])
            views = []
            from util.evaluation_pairwise import comparison_sample_matches
            for sample in samples:
                if comparison_sample_matches(sample, selection, query, mode=review_mode):
                    views.append(sample)
            page = max(0, min(int(page), max(0, (len(views) - 1) // 8)))
            view.update(samples=views[page * 8:page * 8 + 8], total=len(views), page=page)
        vault = vault_for(self.workspace)
        jobs = sorted((j for j in self.operations.jobs.values() if j.get('project_id', '').startswith('evaluation:')),
                      key=lambda j: j['created'], reverse=True)[:20]
        paths = {j['id']: j['result']['path'] for j in jobs if j['status'] == 'complete' and (j.get('result') or {}).get('path')}
        if view:
            paths['run'] = view['path']
        return redact({**cache, 'view': view or None, 'jobs': jobs, 'paths': paths,
                       'active': self.operations.active or None, 'allow_providers': self.allow_providers,
                       'draft': read_json(self.root / 'draft.json', {}),
                       'credentials': [{'name': n, 'endpoint': r['endpoint'], 'keyless': r['keyless']} for n, r in vault['keys'].items()]},
                      [r['secret'] for r in vault['keys'].values()])

    def draft(self, values):
        if not isinstance(values, dict) or len(json.dumps(values)) > 100_000:
            raise ValueError('Evaluation setup is too large.')
        allowed = {'source', 'candidates', 'settings', 'content_selection'}
        if set(values) - allowed:
            raise ValueError('Unknown evaluation setup field.')
        # Candidate drafts contain settings and names, never credential values.
        for row in values.get('candidates', []):
            if set(row) - {'provider', 'model', 'label', 'endpoint', 'key_name', 'execution', 'reasoning_effort', 'max_output_tokens'}:
                raise ValueError('Unknown candidate setting.')
        atomic_json(self.root / 'draft.json', values)
        return {'saved': True}

    def action(self, action, run_id='', options=None, preview_job=''):
        if action not in LABELS:
            raise ValueError('Choose a supported evaluation action.')
        if action in {'submit', 'refresh', 'models'} and not self.allow_providers:
            raise ValueError('Provider operations are disabled in this session.')
        if action not in {'catalog', 'scan', 'prepare', 'archive_import', 'legacy_import', 'models'} and not run_id:
            raise ValueError('Select a saved evaluation first.')
        options = options or {}
        if not isinstance(options, dict) or len(json.dumps(options)) > 200_000:
            raise ValueError('Evaluation options are invalid.')
        plan = {'kind': 'evaluation', 'workspace': str(self.workspace), 'project_id': 'evaluation:' + run_id,
                'run_id': run_id, 'action': action, 'label': LABELS[action], 'options': options,
                'network': self.allow_providers and action in {'submit', 'refresh', 'estimate', 'prepare', 'models'}}
        if run_id:
            plan['revision'] = revision(run_path(self.root, run_id))
        if action in {'submit', 'review_export'}:
            job = self.operations.jobs.get(preview_job) or {}
            expected = 'estimate' if action == 'submit' else 'review_preview'
            result = job.get('result') or {}
            if (job.get('status') != 'complete' or job.get('action') != expected or result.get('run_id') != run_id
                    or result.get('revision') != plan.get('revision')):
                raise ValueError('Preview this saved run again before continuing.')
            if action == 'submit' and result.get('credential_signature') != credential_signature(vault_for(self.workspace)):
                raise ValueError('Saved credentials changed. Review submission again.')
            plan['options'] = result.get('options', {})
            plan['credential_signature'] = result.get('credential_signature')
        if action in {'archive_import', 'review_import', 'calibration'}:
            source = Path(str(options.get('path', ''))).expanduser()
            if source.is_symlink() or not source.is_file() or source.stat().st_size > 256_000_000:
                raise ValueError('Choose a regular evaluation file below 256 MB.')
            plan['input_hash'] = digest(source.read_bytes())
            plan['options']['path'] = str(source.resolve())
        return self.operations.start(plan)


def catalog(project, engine):
    from util.evaluation_pairwise import DEFAULT_POLICY
    from util.model_catalog import ModelCatalogCore
    result = {'runs': engine.list_runs(project), 'defaults': list(engine.DEFAULT_CANDIDATES),
              'content_groups': engine.CONTENT_SOURCE_GROUPS, 'policy': DEFAULT_POLICY, 'model_suggestions': ModelCatalogCore.DEFAULTS}
    for row in result['runs']:
        saved = read_json(Path(row['run_dir']) / 'state.json', {})
        if saved.get('desktop_source'):
            row['source_name'] = Path(saved['desktop_source']).name
    from .workflow_actions import json_value
    atomic_json(project / 'desktop-index.json', json_value(result))


def cache_view(project, root, engine):
    from util import evaluation_pairwise as paired
    state, manifest = engine.load_run(root)
    comparison = engine.load_comparison_data(root)
    choices = engine.blind_review_candidates(root, include_unavailable=True) if state['status'] in {'completed', 'failed'} else []
    labels = {c['id']: engine.candidate_label(c) for c in state['candidates']}
    campaign = state.get('paired_review')
    report = campaign.get('analysis') or paired.summarize(campaign) if campaign else None
    value = {'run_id': state['run_id'], 'path': str(root), 'revision': revision(root),
             'state': state, 'comparison_candidates': comparison['candidates'], 'samples': comparison['samples'],
             'choices': choices, 'context': engine.context_audit(manifest), 'requests': len(manifest['executions']),
             'paired_report': report, 'paired_summary': paired.format_summary(campaign, labels) if campaign else ''}
    atomic_json(project / 'views' / (state['run_id'] + '.json'), value)


def candidates_with_credentials(candidates, vault):
    rows = []
    allowed = {'provider', 'model', 'label', 'endpoint', 'key_name', 'execution', 'reasoning_effort', 'max_output_tokens'}
    for row in candidates:
        if not isinstance(row, dict) or set(row) - allowed:
            raise ValueError('Unknown comparison candidate setting.')
        key = vault['keys'].get(row.get('key_name'))
        if not key or row.get('endpoint', '').rstrip('/') != key['endpoint'].rstrip('/'):
            raise ValueError('Each candidate needs a saved credential for its exact API URL.')
        rows.append({**row, 'keyless': key['keyless']})
    return rows


def credentials(state, vault):
    result = {}
    for row in state['candidates']:
        if row.get('status') in {'completed', 'failed'}:
            continue
        key = vault['keys'].get(row.get('key_name'))
        if not key or key['endpoint'].rstrip('/') != row.get('endpoint', '').rstrip('/'):
            raise ValueError('The original named credential and API URL must still be available for every unfinished candidate.')
        if not key['secret'] and not key['keyless']:
            raise ValueError('The original credential has no saved key.')
        result[row['id']] = key['secret']
    return result


def run_action(plan, log):
    workspace = Path(plan['workspace'])
    project = workspace / 'evaluation'
    project.mkdir(parents=True, exist_ok=True)
    os.chdir(project)
    os.environ.update(PYTHON_DOTENV_DISABLED='1', TIKTOKEN_CACHE_DIR=str(Path(__file__).resolve().parents[2] / 'data/tokenizers'))
    if not plan['network'] or os.getenv('DAZEDTL_TEST_OFFLINE') == '1':
        import socket
        def blocked(*args, **kwargs):
            raise RuntimeError('Network access is disabled for this local evaluation action.')
        socket.create_connection = socket.socket.connect = socket.socket.connect_ex = blocked
    from .settings import SettingsStore, validate_values
    from util import api_keys
    api_keys.API_KEYS_PATH = SettingsStore(workspace).vault_path
    vault = vault_for(workspace)
    secrets = [r['secret'] for r in vault['keys'].values() if r['secret']]
    values = validate_values(SettingsStore(workspace).read()['values'])
    os.environ.update({k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in values.items()})
    os.environ.update(key='not-needed', API_KEY_OPTIONAL='true')
    # Redact before the operation's protocol and durable logs see provider errors.
    streams = sys.stdout, sys.stderr
    class CleanStream:
        def __init__(self, stream): self.stream = stream
        def write(self, text): return self.stream.write(redact(text, secrets))
        def flush(self): return self.stream.flush()
        def isatty(self): return False
    sys.stdout, sys.stderr = (CleanStream(s) for s in streams)
    def clean_log(message): log(redact(message, secrets))
    try:
        return _execute(plan, project, vault, clean_log, getattr(log, 'stopped', lambda: False))
    except Exception as exc:
        raise (InterruptedError if isinstance(exc, InterruptedError) else ValueError)(redact(str(exc), secrets)) from None
    finally:
        sys.stdout, sys.stderr = streams


def _execute(plan, project, vault, log, stopped):
    action, options = plan['action'], plan['options']
    root = run_path(project, plan['run_id']) if plan['run_id'] else None
    if root and revision(root) != plan['revision']:
        raise ValueError('This evaluation changed after the action was requested. Reload it first.')
    if plan.get('credential_signature') and credential_signature(vault) != plan['credential_signature']:
        raise ValueError('Credentials changed after cost review. Review again before sending requests.')
    if plan.get('input_hash') and digest(Path(options['path']).read_bytes()) != plan['input_hash']:
        raise ValueError('The selected import file changed. Select it again.')
    from util import evaluation as engine
    from .workflow_actions import json_value
    result = {}
    if action == 'models':
        from util.model_catalog import ModelCatalog
        row = candidates_with_credentials([options['candidate']], vault)[0]
        discovery = ModelCatalog(vault['keys'][row['key_name']]['secret'], row['endpoint'], row['provider'])
        discovered, errors = [], []
        discovery.models_fetched.connect(discovered.extend)
        discovery.fetch_error.connect(errors.append)
        discovery.run()
        if errors:
            raise ValueError('\n'.join(errors))
        result.update(models=discovered, model_source={k: row[k] for k in ('key_name', 'endpoint', 'provider')})
    elif action in {'scan', 'prepare'}:
        source = Path(options['source']).expanduser().resolve(strict=True)
        if source.is_relative_to(project.parent) or project.parent.is_relative_to(source):
            raise ValueError('Choose a game folder outside this desktop profile.')
        data = engine.resolve_rpgmaker_data_dir(source)
        if not data.resolve().is_relative_to(source):
            raise ValueError('The selected data folder must remain inside its source game.')
        files = sorted(data.glob('*.json'))
        if any(p.is_symlink() or not p.is_file() or p.stat().st_size > 100_000_000 for p in files):
            raise ValueError('Game JSON inputs must be regular files below 100 MB.')
        source_hash = digest(json.dumps({p.name: digest(p.read_bytes()) for p in files}, sort_keys=True).encode())
        pool = engine.scan_corpus(data)
        selection = engine.normalize_content_selection(options.get('content_selection'))
        selected = len(engine._filter_corpus(pool, selection))
        result.update(inventory=engine.content_inventory(data, _pool=pool), selected=selected, source=str(source),
                      source_hash=source_hash, selection=options.get('content_selection', {}))
        if action == 'prepare':
            if options.get('source_hash') != source_hash:
                raise ValueError('Inspect the current game files before preparing this evaluation.')
            config = options.get('settings', {})
            limits = {'target_segments': (60, 5000), 'stability_samples': (0, 500), 'repetitions': (1, 10),
                      'batch_size': (1, 2147483647), 'budget_usd': (1, 100)}
            if (not isinstance(config, dict) or set(config) - limits.keys()
                    or any(type(v) not in ((int, float) if k == 'budget_usd' else (int,))
                           or not limits[k][0] <= v <= limits[k][1] for k, v in config.items())):
                raise ValueError('Choose valid evaluation size, repetition, and budget settings.')
            if selected < 60 or not 60 <= config.get('target_segments', 360) <= selected:
                raise ValueError(f'Select at least 60 eligible lines and a target no larger than the {selected} available lines.')
            rows = candidates_with_credentials(options['candidates'], vault)
            # Shared prompt loading migrates portable context. Do that only in
            # an isolated snapshot, never in the original game selected for evaluation.
            from .manual import ManualJobs
            with tempfile.TemporaryDirectory(prefix='context-', dir=project) as temporary:
                temp = Path(temporary)
                context_plan = {'context_source': str(engine.resolve_evaluation_game_root(source) or source)}
                ManualJobs.__new__(ManualJobs)._snapshot_context(temp, context_plan, project.parent)
                root, saved = engine.prepare_run(project, data, rows, game_root=temp / 'game', content_selection=selection,
                                                 stability_segments=0, **config)
                saved['desktop_source'] = str(source)
                engine._atomic_write_json(root / 'state.json', saved)
            result['message'] = 'Evaluation prepared locally. Review costs before sending requests.'
    elif action == 'legacy_import':
        source = Path(options['path']).expanduser().resolve(strict=True)
        if not (source / 'state.json').is_file() or not (source / 'manifest.json').is_file():
            raise ValueError('Choose one saved evaluation folder containing state.json and manifest.json.')
        if source.is_relative_to(project) or any(p.is_symlink() for p in source.rglob('*')):
            raise ValueError('Choose an original evaluation folder with regular files outside this profile.')
        with tempfile.TemporaryDirectory(prefix='legacy-', dir=project) as temporary:
            archive = engine.export_run_archive(source, Path(temporary) / 'legacy.dazedeval')
            root = engine.import_run_archive(project, archive)
        result['message'] = 'Legacy run imported. Active provider jobs remain paused until their original credentials are bound.'
    elif action == 'archive_import':
        root = engine.import_run_archive(project, options['path'])
    elif action == 'bind':
        bindings = {}
        for candidate, name in options.get('bindings', {}).items():
            key = vault['keys'].get(name)
            if not key:
                raise ValueError('Select an available local credential for every unfinished candidate.')
            bindings[candidate] = {'key_name': name, 'endpoint': key['endpoint'], 'keyless': key['keyless']}
        engine.bind_imported_credentials(root, bindings)
    elif action == 'estimate':
        state, manifest = engine.refresh_run_estimates(root)
        if state.get('credential_binding_required') or state['status'] not in {'prepared', 'partially_submitted'}:
            raise ValueError('Bind imported credentials or select a prepared/resumable run before reviewing submission.')
        credentials(state, vault)
        result.update(approval={'candidates': state['candidates'], 'requests': len(manifest['executions']),
                                'budget': state['budget_usd_per_model']}, credential_signature=credential_signature(vault))
    elif action in {'submit', 'refresh'}:
        state, _ = engine.load_run(root)
        keys = credentials(state, vault)
        if state.get('credential_binding_required'):
            raise ValueError('Bind the imported run to its original credentials first.')
        if action == 'submit':
            if state['status'] not in {'prepared', 'partially_submitted'}:
                raise ValueError('This saved evaluation is not awaiting submission.')
            engine.submit_run(root, keys, log, should_stop=stopped)
        else:
            if state['status'] == 'imported_paused':
                engine.resume_imported_run(root)
            engine.refresh_run(root, keys, log)
        root = engine.locate_run(project, plan['run_id']) or root
    elif action in {'review_preview', 'review_export'}:
        paired = options.get('mode', 'paired') == 'paired'
        review_options = {k: v for k, v in options.items() if k in {'stage', 'candidate_ids', 'policy', 'new_campaign', 'challenge_samples'}}
        if paired:
            preview = engine.paired_review_preview(root, **review_options)
        else:
            preview = engine.blind_review_coverage(root, options.get('candidate_ids'))
        result.update(preview={k: v for k, v in preview.items() if k != 'metadata'}, options=options)
        if action == 'review_export':
            destination = project / 'exports' / uuid.uuid4().hex
            destination.mkdir(parents=True)
            path = (engine.export_paired_review(root, destination / 'paired_review.csv', **review_options) if paired
                    else engine.export_blind_review(root, destination / 'blind_review.csv', options.get('candidate_ids'), judge_check=options.get('stage') == 'judge_check'))
            result.update(path=str(path), review=True)
            atomic_json(root / 'desktop-last-review.json', {'path': str(path), 'hash': digest(path.read_bytes())})
    elif action == 'review_import':
        result['review'] = engine.import_blind_review(root, options['path'], reviewer=options.get('reviewer', ''), reviewer_kind=options.get('reviewer_kind', 'unspecified'))
    elif action == 'calibration':
        result['calibration'] = engine.load_review_calibration(root, options['path'])
    elif action == 'archive_export':
        destination = project / 'exports' / uuid.uuid4().hex / (root.name + '.dazedeval')
        result['path'] = str(engine.export_run_archive(root, destination))
    elif action == 'skill':
        from util.skills import load_clipboard_skill
        from util.evaluation_pairwise_io import is_paired_csv
        saved = read_json(root / 'desktop-last-review.json', {})
        path = Path(saved.get('path', ''))
        if not path.is_file() or not path.resolve().is_relative_to(project / 'exports'):
            state, _ = engine.load_run(root)
            campaign = (state.get('paired_review') or {}).get('campaign_id')
            names = [e.get('file', '') for e in reversed(list(state.get('paired_exports', {}).values()))
                     if e.get('campaign_id') == campaign]
            names.append('blind_review.csv')
            path = next((root / name for name in names if Path(name).name == name and (root / name).is_file()), Path())
        if not path.is_file() or path.is_symlink():
            raise ValueError('Export a blind review from this run before copying its instructions.')
        if is_paired_csv(path):
            text = load_clipboard_skill('evaluation_pairwise_review.md').replace('{{PAIRED_REVIEW_CSV}}', str(path))
        else:
            text = load_clipboard_skill('evaluation_csv_review.md')
            context = engine.export_blind_review_context(root, path.parent)
            for token, target in zip(('BLIND_REVIEW_CSV', 'REVIEW_SYSTEM_PROMPT', 'REVIEW_GLOSSARY', 'REVIEW_SFX_REFERENCE'), (path, *context)):
                text = text.replace('{{' + token + '}}', str(target))
        result['text'] = text
    # A process can close after recording completion and before moving the
    # working run into its archive. Resolve that move before caching paths or
    # issuing a new preview revision.
    maintenance = engine.maintain_evaluation_storage(project)
    if root:
        root = next((target for source, target in maintenance['moved'] if source == root), root)
        root = engine.locate_run(project, root.name) or root
        cache_view(project, root, engine)
        result.update(run_id=root.name, revision=revision(root))
    catalog(project, engine)
    return json_value(redact(result, [r['secret'] for r in vault['keys'].values()]))
