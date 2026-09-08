"""Create the requested local Projects repository; no remote/network operations."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
STAGE = HERE / 'tropical-chase-en'
DEST = Path('C:/Users/sw/Desktop/Projects/tropical-chase-en')

def main():
    manifest = json.loads((HERE / 'project_manifest.json').read_text(encoding='utf-8'))
    if DEST.exists():
        raise ValueError('Project destination already exists; refusing to overwrite')
    for rel, expected in manifest['files'].items():
        if hashlib.sha256((STAGE / rel).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Staging changed: {rel}')
    DEST.mkdir()
    for rel in manifest['files']:
        target = DEST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(STAGE / rel, target)
    def git(*args):
        result = subprocess.run(['git', '-C', str(DEST), *args], capture_output=True, text=True, encoding='utf-8')
        if result.returncode:
            raise ValueError(result.stderr)
        return result.stdout.strip()
    git('init', '-b', 'main')
    git('config', 'core.autocrlf', 'false')
    for key in ['user.name', 'user.email']:
        identity = subprocess.run(['git', '-C', 'C:/Users/sw/Desktop/Projects/musi-dream-en', 'config', '--get', key], capture_output=True, text=True, encoding='utf-8')
        if identity.returncode or not identity.stdout.strip():
            raise ValueError('The reference repository has no configured Git identity')
        git('config', key, identity.stdout.strip())
    git('add', '--all')
    tracked = set(git('ls-files').splitlines())
    if tracked != set(manifest['files']):
        raise ValueError('Git index differs from the reviewed allowlist')
    git('commit', '-m', 'Initial English patch')
    if git('status', '--porcelain'):
        raise ValueError('Repository is not clean')
    report = {'path': str(DEST), 'branch': git('branch', '--show-current'),
              'commit': git('rev-parse', 'HEAD'), 'tracked_files': len(tracked),
              'remote_configured': bool(git('remote')), 'clean': True}
    (HERE / 'repository.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
