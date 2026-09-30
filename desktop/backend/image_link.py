"""Bind desktop documents to portable game image jobs without importing OpenCV."""
import json
import shutil
from pathlib import Path
from .project import atomic_json, digest
from .image_document import desktop_block, portable_block


def beneath(root, relative):
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError('An image path points outside its editable workspace.')
    return path


def read_job(root):
    path = beneath(root, '.dazedtl/image_job.json')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('format') != 'dazedtl-image-job' or data.get('version') not in (1, 2, 3, 4):
        raise ValueError('This portable image job has an unsupported format. No edits were written.')
    for entry in data.get('images', []):
        beneath(root, entry['image'])
    return data


def signature(entry):
    return digest(json.dumps(entry, sort_keys=True, ensure_ascii=False).encode())


def files(root, relative):
    paths = {key: beneath(root, f'.dazedtl/{key}/{relative}') for key in ('original', 'paint', 'cut')}
    paths['editable'] = beneath(root, relative)
    paths['source'] = paths['original'] if paths['original'].is_file() else paths['editable']
    return paths


def file_hashes(paths):
    return {key: digest(path.read_bytes()) if path.is_file() else '' for key, path in paths.items()}


def current(data):
    link = data['link']
    root = Path(link['root'])
    job = read_job(root)
    entry = next((e for e in job['images'] if e['image'] == link['relative']), None)
    paths = files(root, link['relative'])
    if entry is None or signature(entry) != link['entry_hash'] or file_hashes(paths) != link['files']:
        raise ValueError('The portable image or its layers changed elsewhere. Reopen it from the image gallery before saving or rendering.')
    return root, job, entry, paths


def sync(data, *, approved=False):
    root, job, entry, paths = current(data)
    blocks = [portable_block(block) for block in data['blocks']]
    def review_identity(block):
        return {key: block.get(key, default) for key, default in [('id', ''), ('box', []), ('source', ''), ('skip', False), ('angle', 0)]}
    before = [review_identity(b) for b in entry['blocks']]
    after = [review_identity(b) for b in blocks]
    entry.update(blocks=blocks, strokes=data['strokes'], width=data['width'], height=data['height'])
    if before != after:
        entry['status'] = 'needs_review'
    if approved:
        entry['status'] = 'rendered'
    job['root'] = str(root)
    atomic_json(root / '.dazedtl/image_job.json', job)
    data['status'] = entry['status']
    data['link'].update(entry_hash=signature(entry), files=file_hashes(files(root, entry['image'])))


def attach(store, project_id, root, entry):
    import base64
    paths = files(root, entry['image'])
    raw = paths['source'].read_bytes()
    data = store.import_image(project_id, Path(entry['image']).name, 'data:image/png;base64,' + base64.b64encode(raw).decode(), str(root / entry['image']))
    folder = store.folder(project_id, data['id'])
    data = store.read(project_id, data['id'])
    # Explicit reopening adopts the current portable record. Other images stay intact.
    data.update(blocks=[desktop_block(b) for b in entry['blocks']], strokes=entry.get('strokes', []), words=entry.get('words', []),
                status=entry['status'], name=entry['image'], revision=data['revision'] + 1,
                preview_revision=None, approved_revision=None,
                link={'root': str(root), 'relative': entry['image'], 'entry_hash': signature(entry), 'files': file_hashes(paths)})
    for key in ('paint', 'cut'):
        dest = folder / (key + '.png')
        if paths[key].is_file():
            shutil.copyfile(paths[key], dest)
        else:
            dest.unlink(missing_ok=True)
    atomic_json(folder / 'image.json', data)
    return data['id']
