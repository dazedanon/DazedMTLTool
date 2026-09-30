"""Durable image discovery, OCR and portable-job operations for any engine."""
import base64
import json
from pathlib import Path
import uuid
from .project import atomic_json, digest
from .workflow_actions import json_value

LABELS = {'scan': 'Scan game images', 'editable': 'Make images editable', 'delete': 'Delete editable copies',
          'patch': 'Prepare images for the game', 'migrate': 'Migrate legacy editable images',
          'edit': 'Open portable image editor', 'ocr': 'Read image text', 'confirm': 'Confirm reviewed image text', 'unconfirm': 'Mark image text for review',
          'exchange': 'Prepare image-text translation', 'collect': 'Collect image-text translations',
          'restore': 'Restore untranslated editable images', 'resources': 'Inspect image tools',
          'install': 'Install selected image tools', 'skill': 'Prepare image translation handoff'}


class AssetProjects:
    def __init__(self, workspace, operations):
        self.workspace = Path(workspace)
        self.root = self.workspace / 'asset-projects'
        self.operations = operations
        self.projects = {p.parent.name: json.loads(p.read_text()) for p in self.root.glob('*/project.json')}
        selected = self.root / 'selection.json'
        self.current = json.loads(selected.read_text()).get('id', '') if selected.is_file() else ''

    def record(self, identity):
        if identity not in self.projects:
            raise ValueError('Choose an image project first.')
        return self.projects[identity]

    def open(self, source, engine='auto', image_root=''):
        from util.image_manager import detect_image_engine, get_image_profile, normalize_generic_image_root
        root = Path(source).expanduser().resolve(strict=True)
        if not source or not root.is_dir() or root.is_relative_to(self.workspace) or self.workspace.is_relative_to(root):
            raise ValueError('Choose a game outside the desktop profile.')
        detection = detect_image_engine(root)
        engine = detection.engine_id if engine == 'auto' else engine
        get_image_profile(engine)
        image_root = str(normalize_generic_image_root(root, image_root or root)) if engine == 'generic' else ''
        record = next((r for r in self.projects.values() if (r['source'], r['engine'], r['image_root']) == (str(root), engine, image_root)), None)
        if record is None:
            record = {'id': uuid.uuid4().hex, 'source': str(root), 'engine': engine, 'image_root': image_root, 'detection': detection.reason}
            self.projects[record['id']] = record
            atomic_json(self.root / record['id'] / 'project.json', record)
        self.current = record['id']
        atomic_json(self.root / 'selection.json', {'id': self.current})
        return self.state()

    def state(self, project_id='', query='', stage='all', folder='', page=0):
        record = self.projects.get(project_id or self.current)
        jobs = sorted((j for j in self.operations.jobs.values() if record and j['project_id'] == record['id']), key=lambda j: j['created'], reverse=True)
        assets, folders, total = [], [], 0
        if record:
            cache = self.root / record['id'] / 'scan.json'
            assets = json.loads(cache.read_text()) if cache.is_file() else []
            folders = sorted({str(Path(a['relative']).parent) for a in assets})
            total = len(assets)
            assets = [a for a in assets if query.casefold() in a['relative'].casefold() and
                      (stage == 'all' or stage == 'editable' and a['editable'] or stage == 'runtime' and not a['editable']) and
                      (not folder or str(Path(a['relative']).parent) == folder)]
        count = len(assets)
        page = min(max(0, int(page)), max(0, (count - 1) // 32))
        selected = assets[page * 32:page * 32 + 32]
        return {'project': record, 'projects': list(self.projects.values()), 'assets': selected, 'folders': folders, 'count': count,
                'total': total, 'page': page, 'pages': max(1, (count + 31) // 32), 'jobs': jobs[:20],
                'active': self.operations.active, 'legacy': bool(record and (Path(record['source']) / 'DazedTL_Images').is_dir()),
                'paths': {'game': record['source'], 'editable': str(Path(record['source']) / '.dazedtl/images')} if record else {}}

    def thumbnails(self, project_id, ids):
        from util.image_manager import scan_profile_assets, thumbnail_profile_png_bytes
        from util.rpgmaker_images import read_encryption_key
        record = self.record(project_id)
        if not isinstance(ids, list) or len(ids) > 32:
            raise ValueError('Request one page of thumbnails at a time.')
        key = None
        try:
            key = read_encryption_key(record['source']) if record['engine'] == 'rpgmaker_mvmz' else None
        except (ValueError, FileNotFoundError):
            pass
        result = {}
        for asset in scan_profile_assets(record['engine'], record['source'], record['image_root'] or None):
            if asset.asset_id in ids:
                try:
                    raw = thumbnail_profile_png_bytes(record['engine'], asset, key)
                    result[asset.asset_id] = {'url': 'data:image/png;base64,' + base64.b64encode(raw).decode()}
                except Exception as exc:
                    result[asset.asset_id] = {'error': str(exc)}
        return result

    def action(self, project_id, action, ids, options, allow_network):
        record = self.record(project_id)
        if action not in LABELS or not isinstance(ids, list) or len(ids) > 10000 or any(not isinstance(i, str) for i in ids):
            raise ValueError('Invalid image action or selection.')
        if action == 'delete' and not ids:
            raise ValueError('Select the editable copies to delete.')
        if action == 'ocr' and options.get('engine') not in {'lens', 'rapidocr'}:
            raise ValueError('Choose Google Lens or local RapidOCR.')
        if action == 'ocr' and options.get('engine') == 'lens' and not allow_network or action == 'install' and not allow_network:
            raise ValueError('Enable provider/network operations before using online OCR or downloading tools.')
        return self.operations.start({'kind': 'assets', 'project_id': project_id, **record, 'workspace': str(self.workspace),
                                      'action': action, 'label': LABELS[action], 'ids': ids, 'options': options,
                                      'network': bool(allow_network and (action == 'install' or action == 'ocr' and options.get('engine') == 'lens'))})


def run_action(plan, log):
    from util import image_manager as manager
    from util.rpgmaker_images import read_encryption_key, remove_editable_assets, migrate_legacy_editable_workspace
    root = Path(plan['source']).resolve(strict=True)
    workspace = Path(plan['workspace'])
    target = workspace / 'asset-projects' / plan['project_id']
    editable = manager.editable_workspace_root(root)
    engine, action = plan['engine'], plan['action']
    log(plan['label'])
    if not plan.get('network'):
        import socket
        def offline(*args, **kwargs):
            raise RuntimeError('This image action is local. Install required OCR models through Image tools before running it.')
        socket.create_connection = socket.socket.connect = socket.socket.connect_ex = offline
    key = None
    try:
        key = read_encryption_key(root) if engine == 'rpgmaker_mvmz' else None
    except (ValueError, FileNotFoundError):
        pass
    assets = manager.scan_profile_assets(engine, root, plan['image_root'] or None)
    chosen = [a for a in assets if a.asset_id in plan['ids']] if plan['ids'] else assets
    if set(plan['ids']) - {a.asset_id for a in chosen}:
        raise ValueError('An image disappeared since the scan. Scan again before retrying.')
    result = {}
    if action in {'editable', 'patch', 'delete'}:
        if action != 'editable':
            chosen = [a for a in chosen if a.has_plain]
        if not chosen:
            raise ValueError('No matching images are available for this action.')
        if action == 'editable':
            output = manager.make_profile_assets_editable(engine, root, chosen, key, progress=log)
        elif action == 'patch':
            output = manager.prepare_profile_assets_for_patch(engine, root, chosen, key, progress=log)
        else:
            output = remove_editable_assets(root, chosen, progress=log)
        result.update(result=json_value(output), ok=not output.errors, message='; '.join(output.errors) if output.errors else f'{output.completed} image(s) completed; {output.skipped} unchanged.')
    elif action == 'migrate':
        result['moved'] = migrate_legacy_editable_workspace(root)
    elif action in {'edit', 'ocr', 'confirm', 'unconfirm', 'exchange', 'collect', 'restore'}:
        from util.imagetools.job import Job, apply_flags
        from util.imagetools import render, exchange
        from .image_link import read_job, attach, beneath
        from .images import ImageStore
        if (editable / '.dazedtl/image_job.json').is_file():
            read_job(editable)  # Reject unsupported versions and escaping paths before loading.
        job = Job.load(editable)
        relpaths = [str(a.relative_png).replace('\\', '/') for a in chosen if a.has_plain]
        if not relpaths:
            raise ValueError('Make images editable before opening their text job.')
        job.sync(relpaths)
        selected = [job.find(p) for p in relpaths]
        for entry in selected:
            beneath(editable, entry.relpath)
        if action == 'ocr':
            from util.imagetools.ocr import get_engine
            ocr = get_engine(plan['options']['engine'])
            errors = []
            for entry in selected:
                log('Reading ' + entry.relpath)
                try:
                    array = render.load_rgba(job.source_path(entry))
                    if array is None:
                        raise ValueError('Cannot read ' + entry.relpath)
                    entry.height, entry.width = array.shape[:2]
                    entry.adopt(ocr.read(array))
                    apply_flags(entry)
                except Exception as exc:
                    entry.status, entry.error = 'error', str(exc)
                    errors.append(entry.relpath + ': ' + str(exc))
                job.save()
            if errors:
                result.update(ok=False, message='\n'.join(errors))
        elif action in {'confirm', 'unconfirm'}:
            for entry in selected:
                if entry.blocks:
                    apply_flags(entry)
                    entry.status = 'confirmed' if action == 'confirm' else 'needs_review'
        elif action == 'exchange':
            # Export only the chosen, human-reviewed images; retain the whole job on disk.
            export_job = Job(job.root, job.language, [e for e in selected if e in job.confirmed()])
            if not export_job.images:
                raise ValueError('Confirm reviewed text before preparing translation.')
            destination = target / 'translation-input/image_text.json'
            exchange.write(export_job, destination)
            atomic_json(target / 'exchange-binding.json', {'input': str(destination), 'input_hash': digest(destination.read_bytes()), 'entries': {e.relpath: digest(json.dumps(e.to_dict(), sort_keys=True).encode()) for e in export_job.images}})
            result['translation_source'] = str(destination.parent)
        elif action == 'collect':
            binding = json.loads((target / 'exchange-binding.json').read_text())
            for name, expected in binding['entries'].items():
                if digest(json.dumps(job.find(name).to_dict(), sort_keys=True).encode()) != expected:
                    raise ValueError('Reviewed image text changed after translation was prepared. Prepare translation again before collecting.')
            path = Path(plan['options'].get('path', '')).expanduser().resolve(strict=True)
            # The exchange reader merges targets only. Explicit path avoids legacy files/ mirroring.
            original_input = Path(binding['input'])
            if digest(original_input.read_bytes()) != binding['input_hash']:
                raise ValueError('The translation input changed after preparation. Prepare it again.')
            expected = json.loads(original_input.read_text(encoding='utf-8'))
            actual = json.loads(path.read_text(encoding='utf-8'))
            if actual.get('format') != expected['format'] or actual.get('root') != expected['root']:
                raise ValueError('This translation belongs to a different image job.')
            def scope(payload):
                regions = {}
                for image in payload.get('images', []):
                    for block in image.get('regions', []):
                        key = (image.get('image'), block.get('id'))
                        if key in regions:
                            raise ValueError('The translation has duplicate image-region identities.')
                        regions[key] = (block.get('source'), block.get('box'))
                return regions
            if scope(actual) != scope(expected):
                raise ValueError('The translation changed its image identities, source text, or region geometry.')
            output = exchange.read(job, path)
            result['result'] = json_value(output)
            result['message'] = '\n'.join(exchange.summarise(output))
        elif action == 'restore':
            for entry in selected:
                log('Restoring ' + entry.relpath)
                render.restore_entry(job, entry)
        job.save()
        if action in {'edit', 'ocr', 'confirm', 'unconfirm', 'collect', 'restore'}:
            raw = read_job(editable)
            ids = []
            for entry in raw['images']:
                if entry['image'] in relpaths:
                    ids.append(attach(ImageStore(workspace), plan['project_id'], editable, entry))
            result['images'] = ids
    elif action in {'resources', 'install'}:
        from util.imagetools import resources
        if action == 'install':
            resources.install([resources.get(key) for key in plan['options'].get('keys', [])], log=log, should_stop=getattr(log, 'stopped', None))
        result['resources'] = [{'key': r.key, 'label': r.label, 'detail': r.detail, 'size': resources.human(resources.estimate([r])),
                                'installed': resources.installed(r), 'default': r.default} for r in resources.available()]
        if resources.ready():
            from util.imagetools.fonts import available_fonts, font_name
            from util.imagetools import inpaint
            result['fonts'] = [{'path': str(p), 'name': font_name(str(p))} for p in available_fonts()]
            result['methods'] = [{'id': m, 'label': inpaint.METHOD_LABELS[m], 'available': inpaint.available(m), 'status': inpaint.status(m)} for m in inpaint.METHODS]
    elif action == 'skill':
        if not any(a.has_plain for a in assets):
            raise ValueError('Make images editable before preparing the translation handoff.')
        result['prompt'] = manager.build_translation_handoff(root, engine, plan['image_root'] or None)
    # Discovery refresh is small and does not import OCR/render unless requested.
    assets = manager.scan_profile_assets(engine, root, plan['image_root'] or None)
    atomic_json(target / 'scan.json', [{'id': a.asset_id, 'relative': str(a.relative_png).replace('\\', '/'),
                                      'editable': a.has_plain, 'encrypted': a.has_encrypted, 'runtime': a.has_runtime_plain} for a in assets])
    return result
