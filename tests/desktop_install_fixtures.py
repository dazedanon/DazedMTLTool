"""Miniature application archives; no installed games or private configuration."""
from pathlib import Path
import hashlib
import json
import zipfile


ENGINES = {
    'rpgmakermvmz.py': 'CODE401 = True\nFIRSTLINESPEAKERS = False\n',
    'csv.py': 'SOURCE_COLUMN = 0\nTARGET_COLUMN = 1\nCSV_DELIMITER = ","\n',
    'wolf.py': 'CODE101 = True\n',
    'srpg.py': 'FIXTEXTWRAP = True\n',
}


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else value.encode())
    return path


def application(root, *, version='new'):
    for name, text in ENGINES.items():
        write(root, 'desktop/engine-defaults/' + name, text)
    write(root, 'desktop/engine-defaults/manifest.json', json.dumps({
        'version': 1, 'files': {name: hashlib.sha256(text.encode()).hexdigest() for name, text in ENGINES.items()},
    }))
    index = '<html><body>' + version + '</body></html>'
    write(root, 'desktop/dist/index.html', index)
    write(root, 'desktop/dist/renderer-manifest.json', json.dumps({'version': 1, 'files': {'index.html': hashlib.sha256(index.encode()).hexdigest()}}))
    write(root, 'desktop/setup-runtimes.json', '{"version": 1}')
    write(root, 'desktop/retired-qt-files.json', '{"version": 1, "files": ["gui/config_tab.py"]}')
    for name in ('START.sh', 'START.bat', 'scripts/setup_desktop.py', 'desktop/electron/main.cjs'):
        write(root, name, version + '\n')
    write(root, 'desktop/bootstrap.py', 'def main():\n    print("ELECTRON_BOOTSTRAP_REACHED")\n    return 0\n')
    return root


def source_zip(source, path, *, sha='b' * 40):
    with zipfile.ZipFile(path, 'w') as archive:
        for file in source.rglob('*'):
            if file.is_file():
                archive.write(file, 'dazedtl/' + file.relative_to(source).as_posix())
        archive.writestr('dazedtl/.git_archival.txt', 'node: ' + sha + '\n')
    return path
