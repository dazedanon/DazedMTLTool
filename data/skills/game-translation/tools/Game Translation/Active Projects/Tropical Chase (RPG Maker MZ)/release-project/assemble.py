"""Assemble the reviewed player-only Git project without changing payload bytes."""
from pathlib import Path
import hashlib
import json
import shutil

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
STAGE = HERE / 'tropical-chase-en'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    if STAGE.exists():
        raise ValueError('Staging folder already exists')
    release = BASE / 'text_translation/release'
    manifest_path = release / 'payload_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    qa = json.loads((BASE / 'reports/final_qa.json').read_text(encoding='utf-8'))
    if not qa['verified_checks_pass'] or qa['version'] != '1.0.1' or qa['artifact_hashes'] != manifest['files'] or qa['payload_manifest_sha256'] != sha(manifest_path):
        raise ValueError('Release evidence mismatch')
    if len(manifest['files']) != 69:
        raise ValueError('Unexpected payload set')
    for rel, expected in manifest['files'].items():
        source = release / 'EnglishPatch' / rel
        if sha(source) != expected or sha(BASE.parent / rel) != expected:
            raise ValueError(f'Payload or installed game mismatch: {rel}')
    STAGE.mkdir()
    for rel in manifest['files']:
        destination = STAGE / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(release / 'EnglishPatch' / rel, destination)
    shutil.copyfile(HERE / 'README.md', STAGE / 'README.md')
    (STAGE / '.gitattributes').write_text('# Preserve the tested patch bytes on every checkout.\n* -text\n', encoding='utf-8')
    names = set(manifest['files']) | {'README.md', '.gitignore', '.gitattributes'}
    directories = {str(parent).replace('\\', '/') for rel in names for parent in Path(rel).parents if str(parent) != '.'}
    ignore = ['# Track only the release patch.', '*']
    ignore += ['!/' + p + '/' for p in sorted(directories, key=lambda p: (p.count('/'), p))]
    ignore += ['!/' + p for p in sorted(names)]
    (STAGE / '.gitignore').write_text('\n'.join(ignore) + '\n', encoding='utf-8')
    files = {p.relative_to(STAGE).as_posix(): sha(p) for p in STAGE.rglob('*') if p.is_file()}
    if set(files) != names:
        raise ValueError('Unexpected staged files')
    report = {'project': 'tropical-chase-en', 'patch_version': manifest['version'],
              'source_release_manifest_sha256': sha(manifest_path), 'runtime_files': 69,
              'image_files': 44, 'files': files, 'payload': manifest['files'],
              'bytes': sum((STAGE / rel).stat().st_size for rel in names)}
    (HERE / 'project_manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ['files', 'payload']}, indent=2))

if __name__ == '__main__':
    main()
