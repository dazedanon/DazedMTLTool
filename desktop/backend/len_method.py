"""Len's saved desktop projects and the existing portable handoff workflow."""
from dataclasses import asdict
import json
from pathlib import Path
import uuid

from util.len_translation import LenProject, BUNDLED_SKILL, load_project, _validate_project
from .project import atomic_json
from .guidance import documents, document_save, valid_document_name
from .workflow_actions import regular

FIELDS = {'mode', 'include_images', 'include_glossary_base', 'install_forge', 'instructions'}
ACTIONS = {'prepare': 'Prepare Len handoff', 'reference_add': 'Add reference translation',
           'reference_pair': 'Add Japanese / English reference pair', 'reference_remove': 'Remove reference registration',
           'reference_build': 'Build reference matches'}


def project_from(record):
    project = LenProject(Path(record['source']), **record['values'])
    _validate_project(project)
    if len(project.instructions.encode()) > 100000:
        raise ValueError('Keep project instructions below 100 KB.')
    return project


class LenMethods:
    def __init__(self, workspace, operations):
        self.workspace = Path(workspace)
        self.root = self.workspace / 'len-method'
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
            raise ValueError("Select a Len project first.")
        return self.projects[identity]

    def persist(self, record):
        atomic_json(self.root / record['id'] / 'project.json', record)

    def open(self, source):
        if not isinstance(source, str) or not source.strip():
            raise ValueError('Choose an existing game folder.')
        project = load_project(Path(source))
        if project.game_root.is_relative_to(self.workspace) or self.workspace.is_relative_to(project.game_root):
            raise ValueError('The game and desktop workspace must be separate folders.')
        record = next((r for r in self.projects.values() if r['source'] == str(project.game_root)), None)
        if not record:
            values = asdict(project)
            values.pop('game_root')
            record = {'id': uuid.uuid4().hex, 'source': str(project.game_root), 'revision': 0, 'values': values, 'documents': {}}
            self.projects[record['id']] = record
            self.persist(record)
        self.current = record['id']
        atomic_json(self.root / 'selection.json', {'id': self.current})
        return self.state()

    def save(self, project_id, revision, values, drafts):
        record = self.record(project_id)
        if revision != record['revision']:
            raise ValueError('The Len project changed elsewhere. Reload before saving.')
        if not isinstance(values, dict) or set(values) != FIELDS:
            raise ValueError('Invalid Len project settings.')
        project_from({**record, 'values': values})
        if not isinstance(drafts, dict) or len(json.dumps(drafts).encode()) > 3500000:
            raise ValueError('Invalid guidance draft.')
        for name, value in drafts.items():
            if not valid_document_name(name) or not isinstance(value, dict) or set(value) != {'text', 'revision'} or not all(isinstance(v, str) for v in value.values()):
                raise ValueError('Invalid guidance draft.')
        record.update(values=values, documents=drafts, revision=revision + 1)
        self.persist(record)
        return record

    def state(self, project_id=''):
        record = self.projects.get(project_id or self.current)
        result = {'project': record, 'projects': [{'id': r['id'], 'source': r['source']} for r in self.projects.values()],
                  'jobs': [], 'active': self.operations.active or None, 'paths': {}}
        if not record:
            return result
        project = project_from(record)
        from util.len_progress import read_progress, empty_progress, metric_display, estimate_display, PHASES, STATES
        try:
            progress = read_progress(project, check_hashes=False)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            progress = {**empty_progress(project), 'warnings': [f'Could not read progress: {exc}']}
        metrics = {}
        for key in ('text', 'reviewed', 'images'):
            metric = progress['metrics']['images' if key == 'images' else 'text']
            value, label, counts = metric_display(metric, 'reviewed' if key == 'reviewed' else 'translated', excluded=key == 'images' and not project.include_images)
            metrics[key] = {'value': value, 'label': label, 'counts': counts}
        from util.reference_games import load_registry
        from util.project_preparation import rpgmaker_layout
        layout = rpgmaker_layout(project.game_root)
        jobs = sorted((j for j in self.operations.jobs.values() if j['project_id'] == record['id']), key=lambda j: j['created'], reverse=True)
        report = project.workspace / 'status.md'
        status = ''
        if report.is_file():
            regular(project.game_root, report)
            with report.open(encoding='utf-8') as handle:
                status = handle.read(250000)
        result.update(progress=progress, metrics=metrics, estimate=estimate_display(progress),
                      phases={key: {'label': PHASES[key], 'status': STATES[value]} for key, value in progress['phases'].items()},
                      status=status, jobs=jobs[:20], references=load_registry(project.game_root)['references'],
                      forge_supported=bool(layout and layout['engine'] == 'MVMZ'),
                      paths={'game': str(project.game_root), 'skill': str(BUNDLED_SKILL / 'SKILL.md'),
                             **({'workspace': str(project.workspace)} if project.workspace.is_dir() else {})})
        return json.loads(json.dumps(result))

    def documents(self, project_id):
        return documents(self.record(project_id)['source'])

    def document_save(self, project_id, name, revision, text):
        record = self.record(project_id)
        result = document_save(record['source'], name, revision, text)
        record['documents'].pop(name, None)
        self.persist(record)
        return result

    def action(self, project_id, revision, action, options):
        record = self.record(project_id)
        if record['revision'] != revision:
            raise ValueError('Project settings changed. Reload before preparing a handoff.')
        if action not in ACTIONS or not isinstance(options, dict):
            raise ValueError('Unknown Len action.')
        if action == 'prepare' and record['documents']:
            raise ValueError('Save the pending guidance drafts to the game before preparing a handoff.')
        project_from(record)
        selected = {}
        if action in {'reference_add', 'reference_pair'}:
            title = str(options.get('title', '')).strip()
            if not title or len(title) > 200:
                raise ValueError('Enter a short reference title.')
            selected['title'] = title
            for key in ('translated', 'original') if action == 'reference_pair' else ('translated',):
                if not isinstance(options.get(key), str) or not options[key].strip():
                    raise ValueError('Choose the reference folders.')
                selected[key] = str(Path(options[key]).expanduser().resolve(strict=True))
        elif action == 'reference_remove':
            from util.reference_games import load_registry
            if options.get('id') not in {r['id'] for r in load_registry(record['source'])['references']}:
                raise ValueError('Choose a registered reference.')
            selected['id'] = options['id']
        return self.operations.start({'kind': 'len', 'project_id': project_id, 'action': action, 'label': ACTIONS[action],
                                      'source': record['source'], 'values': dict(record['values']), 'options': selected,
                                      'workspace': str(self.workspace)})


def run_action(plan, log):
    project = project_from(plan)
    action, options = plan['action'], plan['options']
    log(plan['label'])
    if action == 'prepare':
        from util.len_translation import prepare_project
        handoff = prepare_project(project, desktop_workspace=plan['workspace'])
        return {'handoff': handoff.read_text(encoding='utf-8'), 'values': plan['values'], 'path': str(handoff)}
    from util.reference_games import add_embedded_reference, add_game_pair_reference, remove_reference, prepare_overlaps, inspect_reference_game
    from util.project_preparation import _game_path
    for name in ('reference-games.json', 'reference-index.json', 'reference-overlaps.json'):
        regular(project.game_root, project.game_root / '.dazedtl' / name)
    _game_path(project.game_root, project.game_root / '.dazedtl/reference-data')
    if action == 'reference_add':
        reference = inspect_reference_game(options['translated'])
        if not reference['data']:
            raise ValueError('Choose extracted reference data containing _original translations.')
        return add_embedded_reference(project.game_root, options['title'], reference['data'])
    if action == 'reference_pair':
        return add_game_pair_reference(project.game_root, options['title'], options['original'], options['translated'], log_fn=log)
    if action == 'reference_remove':
        remove_reference(project.game_root, options['id'])
        return {'removed': options['id']}
    if action == 'reference_build':
        data = inspect_reference_game(project.game_root)['data']
        if not data:
            raise ValueError('Extract supported game data before building reference matches.')
        return prepare_overlaps(project.game_root, data, force=True)
    raise ValueError('Unknown Len action.')
