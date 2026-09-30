"""Durable desktop adapters for the production Git version-update workflow."""
import json
from pathlib import Path
import uuid

from .project import atomic_json, digest
from .workflow_actions import json_value

DEFAULTS = {'original': '', 'original_version': '', 'official': '', 'version': '', 'baseline': '',
            'patch_overlay': False, 'untranslated': False, 'preserve_game_files': False}
LABELS = {'status': 'Inspect version tracking', 'bootstrap': 'Create version baselines',
          'register': 'Register current translation branch', 'checkout': 'Switch to translation branch',
          'metadata': 'Record baseline version labels', 'preview': 'Preview official update', 'apply': 'Apply reviewed official update',
          'registered': 'Apply registered original and finish assets', 'continue': 'Continue using official conflict files',
          'abort': 'Abort pending cherry-pick', 'post_update': 'Prepare post-update translation handoff'}


class VersionUpdates:
    def __init__(self, workspace, operations):
        self.workspace = Path(workspace)
        self.root = self.workspace / 'version-update'
        self.operations = operations
        self.projects = {}
        self.current = ''
        for path in self.root.glob('*/project.json'):
            record = json.loads(path.read_text(encoding='utf-8'))
            self.projects[record['id']] = record
        selection = self.root / 'selection.json'
        if selection.is_file():
            self.current = json.loads(selection.read_text())['id']

    def record(self, identity):
        if identity not in self.projects:
            raise ValueError('Select a game for version tracking first.')
        return self.projects[identity]

    def persist(self, record):
        atomic_json(self.root / record['id'] / 'project.json', record)

    def open(self, source, preserve=False):
        if not isinstance(source, str) or not source.strip():
            raise ValueError('Choose a game folder.')
        root = Path(source).expanduser().resolve(strict=True)
        if not root.is_dir() or root.is_relative_to(self.workspace) or self.workspace.is_relative_to(root):
            raise ValueError('Choose a game outside the desktop workspace.')
        record = next((r for r in self.projects.values() if r['source'] == str(root)), None)
        if not record:
            record = {'id': uuid.uuid4().hex, 'source': str(root), 'revision': 0,
                      'values': {**DEFAULTS, 'preserve_game_files': preserve or (root / '.dazedtl/len-method/project.json').is_file()}}
            self.projects[record['id']] = record
            self.persist(record)
        elif preserve and not record['values']['preserve_game_files']:
            record['values']['preserve_game_files'] = True
            record['revision'] += 1
            self.persist(record)
        self.current = record['id']
        atomic_json(self.root / 'selection.json', {'id': self.current})
        return self.state()

    def save(self, project_id, revision, values):
        record = self.record(project_id)
        if revision != record['revision']:
            raise ValueError('Version-update settings changed. Reload before saving.')
        if not isinstance(values, dict) or set(values) != set(DEFAULTS):
            raise ValueError('Unknown version-update option.')
        for key, value in values.items():
            if type(value) is not type(DEFAULTS[key]) or isinstance(value, str) and (len(value) > 4096 or '\0' in value):
                raise ValueError('Invalid version-update option.')
        record.update(revision=revision + 1, values=values)
        self.persist(record)
        return record

    def state(self, project_id=''):
        record = self.projects.get(project_id or self.current)
        jobs = sorted((j for j in self.operations.jobs.values() if record and j['project_id'] == record['id']), key=lambda j: j['created'], reverse=True)
        status = next((j['result']['status'] for j in jobs if isinstance(j.get('result'), dict) and j['result'].get('status')), None)
        preview = next(({'job_id': j['id'], **j['result']['preview']} for j in jobs if j['status'] == 'complete' and
                        j['action'] == 'preview' and j.get('result', {}).get('values') == record['values'] and
                        not any(newer['created'] > j['created'] and newer['action'] not in {'status', 'post_update', 'preview'} for newer in jobs)), None) if record else None
        return json.loads(json.dumps({'project': record, 'projects': [{'id': r['id'], 'source': r['source']} for r in self.projects.values()],
                                     'status': status, 'preview': preview, 'jobs': jobs[:20], 'active': self.operations.active or None}))

    def action(self, project_id, revision, action, preview_job=''):
        record = self.record(project_id)
        if record['revision'] != revision or action not in LABELS:
            raise ValueError('Reload the project before running this action.')
        values = dict(record['values'])
        plan = {'kind': 'version', 'project_id': project_id, 'source': record['source'], 'values': values,
                'action': action, 'label': LABELS[action]}
        if action in {'bootstrap', 'register', 'metadata'} and not values['original_version'].strip():
            raise ValueError('Enter the version of the current game.')
        if action == 'bootstrap' and not values['original'].strip() and not values['untranslated']:
            raise ValueError('Choose a matching clean original, or confirm that this game remains untranslated.')
        if action in {'preview', 'apply'} and (not values['official'].strip() or not values['version'].strip()):
            raise ValueError('Choose the new official folder and enter its version.')
        if action == 'apply':
            job = self.operations.jobs.get(preview_job)
            if not job or job['project_id'] != project_id or job['action'] != 'preview' or job['status'] != 'complete':
                raise ValueError('Preview the update before applying it.')
            saved = self.operations.root / preview_job / 'plan.json'
            if saved.is_symlink() or digest(saved.read_bytes()) != job['plan_hash']:
                raise ValueError('The preview changed. Preview the update again.')
            original_plan = json.loads(saved.read_text(encoding='utf-8'))
            if original_plan['values'] != values or original_plan['source'] != record['source']:
                raise ValueError('The update selection changed. Preview it again.')
            plan['preview'] = job['result']['preview']
        return self.operations.start(plan)


def status_value(root):
    from util.version_update import inspect_repository, conflict_paths, local_branch_names
    status = inspect_repository(root)
    return {**json_value(status), 'ready': status.ready, 'conflicts': list(conflict_paths(root)) if status.pending_cherry_pick else [],
            'branches': list(local_branch_names(root)) if status.repo_root else []}


def run_action(plan, log):
    from util import version_update as git
    root = Path(plan['source']).resolve(strict=True)
    values, action = plan['values'], plan['action']
    log(plan['label'])
    payload = {}
    try:
        preserve = values['preserve_game_files'] or (root / '.dazedtl/len-method/project.json').is_file()
        if action == 'bootstrap':
            original = Path(values['original']).expanduser().resolve(strict=True) if values['original'].strip() else root
            if original == root and not values['untranslated']:
                raise ValueError('Confirm the selected game remains untranslated before using it as an original baseline.')
            payload['result'] = git.bootstrap_repository(root, original, values['original_version'], preserve_game_files=preserve)
        elif action == 'register':
            payload['result'] = git.register_translation_branch(root, values['original_version'], preserve_game_files=preserve)
        elif action == 'metadata':
            payload['result'] = git.record_version_metadata(root, values['original_version'])
        elif action == 'checkout':
            payload['result'] = git.checkout_translation_branch(root)
        elif action == 'preview':
            preview = git.preview_official_update(root, values['official'], values['version'], previous_official_game=values['baseline'] or None,
                                                 patch_overlay=values['patch_overlay'])
            payload.update(preview={**json_value(preview), 'content_change_expected': preview.content_change_expected}, values=values)
        elif action == 'apply':
            preview = plan['preview']
            payload['result'] = git.apply_official_update(root, values['official'], values['version'],
                expected_tree=preview['proposed_tree'], expected_original_commit=preview['original_commit'],
                expected_translation_commit=preview['translation_commit'], expected_asset_manifest=preview['proposed_asset_manifest'],
                previous_official_game=values['baseline'] or None, expected_baseline_asset_manifest=preview['baseline_asset_manifest'],
                patch_overlay=values['patch_overlay'])
        elif action == 'registered':
            payload['result'] = git.apply_registered_original(root)
        elif action == 'continue':
            payload['result'] = git.continue_with_official(root)
        elif action == 'abort':
            payload['result'] = git.abort_update(root)
        elif action == 'post_update':
            from util.version_update.handoff import post_update_handoff
            payload.update(post_update_handoff(root))
        elif action != 'status':
            raise ValueError('Unknown version-update action.')
        if isinstance(payload.get('result'), git.UpdateResult):
            payload['complete'] = payload['result'].complete
    except (git.GitWorkflowError, ValueError) as exc:
        payload.update(ok=False, message=str(exc))
    payload['status'] = status_value(root)
    return json_value(payload)
