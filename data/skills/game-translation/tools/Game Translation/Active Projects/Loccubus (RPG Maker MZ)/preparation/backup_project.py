"""Copy this reviewed preparation project to its configured stable tools path."""
import json
import shutil
from pathlib import Path

import tl
from vendor.core import sha, write_json


def main():
    tl.check()
    destination = Path(tl.config()['stable_backup'])
    if destination.exists():
        raise ValueError('Stable destination already exists; refusing to overwrite prior work')
    files = {p.relative_to(tl.BASE).as_posix(): p for p in tl.BASE.rglob('*')
             if p.is_file() and not ({'__pycache__', 'builds', 'source'} & set(p.relative_to(tl.BASE).parts))}
    if any(p.is_symlink() for p in files.values()):
        raise ValueError('Refusing to back up symbolic links')
    hashes = {rel: sha(p.read_bytes()) for rel, p in files.items()}
    for rel, source in files.items():
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if sha(target.read_bytes()) != hashes[rel]:
            raise ValueError('Stable backup verification failed: ' + rel)
    write_json(tl.BASE / 'reports/stable_backup.json', {
        'destination': str(destination), 'verified_files': len(files), 'hashes': hashes,
        'excluded': ['builds/', 'source/ (historical, superseded by authoritative source_snapshot.zip)', '__pycache__/']})
    print(json.dumps({'destination': str(destination), 'verified_files': len(files)}, indent=2))


if __name__ == '__main__':
    main()
