"""Verify the real Git checkout and documented copy-over install/restore."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
GAME = BASE / 'clean_game'
CHECKOUT = HERE / 'checkout'
BACKUP = HERE / 'player_backup'
EXTRA = 'js/plugins/TropicalChaseEnglish.js'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def original_files():
    originals = {rel: (BASE / 'source' / rel, record['sha256']) for rel, record in load(BASE / 'manifest.json')['files'].items()}
    for row in load(BASE / 'image_review/inventory.json'):
        rel = row['path']
        backup = BASE / 'image_translation/backup' / rel
        originals[rel] = (backup if backup.exists() else GAME / rel, row['sha256'])
    if len(originals) != 715:
        raise ValueError('Unexpected original file set')
    return originals

def verify(english):
    manifest = load(HERE / 'project_manifest.json')
    expected = {rel: value[1] for rel, value in original_files().items()}
    if english:
        expected.update(manifest['payload'])
    for rel, value in expected.items():
        if sha(GAME / rel) != value:
            raise ValueError(f'Clean game mismatch: {rel}')
    if not english and (GAME / EXTRA).exists():
        raise ValueError('Added plugin was not removed')
    return len(expected) + (0 if english else 1)

def target(rel):
    path = (GAME / rel).resolve()
    if not path.is_relative_to(GAME.resolve()):
        raise ValueError('Target escaped the isolated game directory')
    return path

def copy_payload():
    manifest = load(HERE / 'project_manifest.json')
    for rel, expected in manifest['payload'].items():
        if sha(CHECKOUT / rel) != expected:
            raise ValueError(f'Checkout changed: {rel}')
    for rel in manifest['payload']:
        path = target(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CHECKOUT / rel, path)
    return verify(True)

def prepare():
    manifest = load(HERE / 'project_manifest.json')
    repo = Path(load(HERE / 'repository.json')['path'])
    if CHECKOUT.exists() or BACKUP.exists():
        raise ValueError('Checkout or backup already exists; refusing to overwrite')
    subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', str(repo), str(CHECKOUT)], check=True)
    tracked = subprocess.check_output(['git', '-C', str(CHECKOUT), 'ls-files', '-z']).decode('utf-8').rstrip('\0').split('\0')
    if set(tracked) != set(manifest['files']):
        raise ValueError('Checkout file allowlist mismatch')
    for rel, expected in manifest['files'].items():
        blob = subprocess.check_output(['git', '-C', str(CHECKOUT), 'show', 'HEAD:' + rel])
        if hashlib.sha256(blob).hexdigest() != expected or sha(CHECKOUT / rel) != expected:
            raise ValueError(f'Git changed payload bytes: {rel}')
    if subprocess.check_output(['git', '-C', str(CHECKOUT), 'status', '--porcelain']).strip():
        raise ValueError('Fresh checkout is not clean')
    archive = HERE / 'Tropical_Chase_English_Patch_1.0.1.zip'
    subprocess.run(['git', '-C', str(CHECKOUT), 'archive', '--format=zip', '--prefix=Tropical_Chase_English_Patch/', '--output=' + str(archive), 'HEAD', 'data', 'img', 'js', 'index.html', 'package.json', 'README.md'], check=True)
    with zipfile.ZipFile(archive) as zipped:
        names = {p for p in zipped.namelist() if not p.endswith('/')}
        expected_names = {'Tropical_Chase_English_Patch/' + rel for rel in set(manifest['payload']) | {'README.md'}}
        if names != expected_names or zipped.testzip() is not None:
            raise ValueError('Archive allowlist or CRC mismatch')
        for rel in set(manifest['payload']) | {'README.md'}:
            if hashlib.sha256(zipped.read('Tropical_Chase_English_Patch/' + rel)).hexdigest() != manifest['files'][rel]:
                raise ValueError(f'Archive bytes differ: {rel}')
    prior = verify(True)
    originals = original_files()
    # Preflight every original before modifying the owned QA copy.
    for rel in manifest['payload']:
        if rel != EXTRA:
            source, expected = originals[rel]
            if sha(source) != expected:
                raise ValueError(f'Original backup mismatch: {rel}')
    for rel in manifest['payload']:
        if rel != EXTRA:
            shutil.copyfile(originals[rel][0], target(rel))
    if sha(target(EXTRA)) != manifest['payload'][EXTRA]:
        raise ValueError('Unexpected plugin at the owned removal path')
    target(EXTRA).unlink()
    restored_before = verify(False)
    for rel in manifest['payload']:
        if rel != EXTRA:
            destination = BACKUP / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(target(rel), destination)
    installed = copy_payload()
    repeated = copy_payload()
    report = {'scope': 'Packaging-only verification of unchanged 1.0.1 runtime bytes.',
              'checkout_files': len(tracked), 'git_blob_and_checkout_hashes_match': True,
              'prior_game_files_verified': prior, 'original_files_verified': restored_before,
              'install_verified': installed, 'repeat_install_verified': repeated,
              'archive': archive.name, 'archive_sha256': sha(archive), 'archive_bytes': archive.stat().st_size,
              'archive_file_entries': len(names), 'archive_crc_and_hashes_match': True}
    (HERE / 'verification_prepare.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))

def finish():
    manifest = load(HERE / 'project_manifest.json')
    native = load(HERE / 'reports/cold_boot.json')
    if not native['Pass'] or native['HarnessLoaded']:
        raise ValueError('Native cold boot did not pass')
    verify(True)
    originals = original_files()
    for rel in manifest['payload']:
        if rel != EXTRA and sha(BACKUP / rel) != originals[rel][1]:
            raise ValueError(f'The player backup changed: {rel}')
    for rel in manifest['payload']:
        if rel != EXTRA:
            shutil.copyfile(BACKUP / rel, target(rel))
    if sha(target(EXTRA)) != manifest['payload'][EXTRA]:
        raise ValueError('Unexpected plugin at the owned removal path')
    target(EXTRA).unlink()
    restored = verify(False)
    reapplied = copy_payload()
    report = load(HERE / 'verification_prepare.json')
    report.update({'restore_from_player_backup_verified': restored, 'reapply_after_restore_verified': reapplied,
                   'native_cold_boot': native, 'pass': True,
                   'gameplay_evidence': 'Prior v1.0.1 native panel/save/route evidence retained because all 69 runtime hashes are identical. No new full playthrough was performed.'})
    (HERE / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'pass': True, 'restored_paths_verified': restored, 'reapplied_paths_verified': reapplied, 'native_launch': True, 'archive': report['archive']}, indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'finish'])
    args = parser.parse_args()
    (prepare if args.action == 'prepare' else finish)()
