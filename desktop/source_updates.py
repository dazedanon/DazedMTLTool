"""Staged source-archive updates for one-click installs, without a Qt process."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from desktop.bootstrap import (archive_path, atomic_json, clean_environment, digest, ensure_electron,
                               ensure_python, ensure_uv, extract_zip, filesystem_path, platform_key, regular_folder,
                               setup_home, setup_lock, verify_engines, verify_renderer)
from util.source_updates import SourceUpdater, UpdateCandidate


def file_hash(file):
    return digest(file) if file.is_file() else None


class SourceInstallation:
    def __init__(self, root, profile):
        self.root = Path(root).resolve()
        self.profile = Path(profile).resolve()
        self.storage = regular_folder(filesystem_path(self.profile / 'source-updates'))
        self.file = self.storage / 'state.json'

    def installed_sha(self):
        marker = self.root / 'data/last_update_sha.txt'
        if marker.is_file():
            return marker.read_text().strip()
        return SourceUpdater._read_archive_sha(self.root / '.git_archival.txt') or SourceUpdater._read_git_sha(self.root)

    def _read(self):
        value = json.loads(self.file.read_text()) if self.file.is_file() else {
            'version': 1, 'available': None, 'staged': None, 'previous': None, 'message': ''}
        if value.get('version') != 1:
            raise ValueError('Unsupported saved application update state.')
        return value

    def _write_sha(self, sha):
        folder = regular_folder(self.root / 'data')
        target = folder / 'last_update_sha.txt'
        if target.is_symlink():
            raise ValueError('The installed-version marker must not be a symbolic link.')
        descriptor, temporary = tempfile.mkstemp(prefix='.version-', dir=folder)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                stream.write(sha)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def state(self):
        value = self._read()
        return {**value, 'current': self.installed_sha(), 'root': str(self.root),
                'revision': hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()}

    def check(self):
        errors = []
        sources = sorted(SourceUpdater.UPDATE_SOURCES, key=lambda source: {'GitGud': 0, 'git.dazedtl.dev': 1, 'GitHub': 2}[source.name])
        for source in sources:
            try:
                sha = SourceUpdater._fetch_source_sha(source)
                value = self._read()
                value['available'] = None if sha == self.installed_sha() else {'sha': sha, 'mirror': source.name}
                value['message'] = 'You are up to date.' if value['available'] is None else 'An application update is available.'
                atomic_json(self.file, value)
                return value['available']
            except Exception as error:
                errors.append(f'{source.name}: {error}')
        raise RuntimeError('Could not check application updates. ' + ' | '.join(errors))

    def destination(self, relative):
        relative = archive_path(relative)
        if not SourceUpdater.should_install_to_root(relative, self.root):
            raise ValueError('An update attempted to replace protected user data.')
        target = self.root / relative
        for current in (target, *target.parents):
            if current == self.root.parent:
                break
            if current.is_symlink() or getattr(current, 'is_junction', lambda: False)():
                raise ValueError('Application updates cannot write through links or junctions.')
        return filesystem_path(target)

    def stage_archive(self, archive, sha, *, prepare_runtimes=True):
        if not isinstance(sha, str) or not 40 <= len(sha) <= 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('An update needs a complete verified commit ID.')
        staged = regular_folder(self.storage / 'staged') / sha
        with tempfile.TemporaryDirectory(prefix='source-', dir=self.storage) as temporary:
            extract = Path(temporary) / 'extract'
            extract_zip(archive, extract)
            source = SourceUpdater.resolve_archive_root(extract)
            for name in ('START.sh', 'START.bat', 'scripts/setup_desktop.py', 'desktop/bootstrap.py',
                         'desktop/setup-runtimes.json', 'desktop/engine-defaults/manifest.json', 'desktop/electron/main.cjs'):
                if not (source / name).is_file():
                    raise ValueError('This archive is not a complete DazedTL desktop update.')
            embedded_sha = SourceUpdater._read_archive_sha(source / '.git_archival.txt')
            if embedded_sha != sha:
                raise ValueError('The archive belongs to a different commit than the selected update.')
            verify_renderer(source)
            verify_engines(source)
            if prepare_runtimes:
                config = json.loads((source / 'desktop/setup-runtimes.json').read_text())
                cache = regular_folder(setup_home())
                with setup_lock(cache):
                    key = platform_key()
                    uv = ensure_uv(config, cache, key)
                    ensure_python(source, config, cache, uv, key)
                    ensure_electron(config, cache, key)
            files = {}
            for file in sorted(source.rglob('*')):
                if file.is_symlink():
                    raise ValueError('Source updates must contain regular files.')
                if not file.is_file():
                    continue
                name = file.relative_to(source).as_posix()
                if SourceUpdater.should_install_to_root(Path(name), self.root):
                    mode = file.stat().st_mode & 0o777
                    if file.suffix in SourceUpdater.EXECUTABLE_SUFFIXES:
                        mode |= 0o111
                    files[name] = {'sha256': digest(file), 'mode': mode}
            if staged.exists():
                if staged.is_symlink():
                    raise ValueError('Update staging cannot use symbolic links.')
                shutil.rmtree(staged)
            shutil.copytree(source, staged / 'files')
            atomic_json(staged / 'manifest.json', {'version': 1, 'sha': sha, 'root': str(self.root), 'files': files})
        value = self._read()
        value.update(staged={'sha': sha}, message='Update downloaded and verified. Save your work and restart to install it.')
        atomic_json(self.file, value)
        return self.state()

    def download(self):
        available = self._read()['available']
        if not available:
            raise ValueError('Check for an application update first.')
        source = next((source for source in SourceUpdater.UPDATE_SOURCES if source.name == available['mirror']), None)
        if source is None:
            raise ValueError('The selected update mirror is no longer available.')
        with tempfile.TemporaryDirectory(prefix='download-', dir=self.storage) as temporary:
            archive = Path(temporary) / 'application.zip'
            SourceUpdater()._download_archive(archive, UpdateCandidate(available['sha'], source))
            return self.stage_archive(archive, available['sha'])

    def _stage(self, sha):
        if not isinstance(sha, str) or not 40 <= len(sha) <= 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('Invalid staged update ID.')
        stage = self.storage / 'staged' / sha
        manifest = json.loads((stage / 'manifest.json').read_text())
        if manifest.get('version') != 1 or manifest.get('sha') != sha or manifest.get('root') != str(self.root):
            raise ValueError('The staged update belongs to another installation.')
        for name, record in manifest['files'].items():
            self.destination(name)
            file = stage / 'files' / archive_path(name)
            if file.is_symlink() or not file.is_file() or digest(file) != record['sha256']:
                raise ValueError('The staged update changed. Download it again before restarting.')
        return stage, manifest

    def schedule(self, action, revision):
        state = self.state()
        if state['revision'] != revision:
            raise ValueError('Update choices changed. Refresh before restarting.')
        if action == 'activate':
            if not state['staged']:
                raise ValueError('Download an update before installing it.')
            self._stage(state['staged']['sha'])
        elif action != 'rollback' or not state['previous']:
            raise ValueError('There is no previous application build to restore.')
        pending = {'version': 1, 'action': action, 'revision': revision, 'root': str(self.root)}
        atomic_json(self.storage / 'pending.json', pending)
        return pending

    def _restore(self, transaction, journal):
        # Validate the whole rollback before touching the first file. A newer
        # user edit must not leave a partially rolled-back application.
        for operation in journal['operations']:
            target = self.destination(operation['path'])
            current = file_hash(target)
            if current not in {operation['before'], operation['after']}:
                raise ValueError('An application file changed after update. Its backup was retained instead of overwriting the newer edit.')
            if operation['before'] is not None:
                original = transaction / 'files' / archive_path(operation['path'])
                if not original.is_file() or digest(original) != operation['before']:
                    raise ValueError('An application rollback backup changed.')
        for operation in reversed(journal['operations']):
            target = self.destination(operation['path'])
            current = file_hash(target)
            if current == operation['before']:
                continue
            if current != operation['after']:
                raise ValueError('An application file changed after update. Its backup was retained instead of overwriting the newer edit.')
            if operation['before'] is None:
                target.unlink(missing_ok=True)
            else:
                original = transaction / 'files' / archive_path(operation['path'])
                if digest(original) != operation['before']:
                    raise ValueError('An application rollback backup changed.')
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + '.rollback-' + uuid.uuid4().hex)
                try:
                    shutil.copy2(original, temporary)
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)

    def recover(self):
        for file in sorted((self.storage / 'transactions').glob('*/journal.json')):
            journal = json.loads(file.read_text())
            if journal.get('status') == 'applying':
                self._restore(file.parent, journal)
                self._write_sha(journal['before_sha'])
                journal['status'] = 'recovered'
                atomic_json(file, journal)
                value = self._read()
                if (value.get('previous') or {}).get('transaction') == file.parent.name:
                    value['previous'] = None
                value.update(staged={'sha': journal['after_sha']}, message='An interrupted update was rolled back. Your files were retained; the downloaded update can be retried.')
                atomic_json(self.file, value)

    def apply_pending(self):
        self.recover()
        pending_file = self.storage / 'pending.json'
        pending = json.loads(pending_file.read_text())
        state = self.state()
        if pending.get('root') != str(self.root) or pending.get('revision') != state['revision']:
            raise ValueError('The pending update is stale. Open the application and select it again.')
        value = self._read()
        before_state = dict(value)
        if pending['action'] == 'rollback':
            previous = state['previous']
            transaction = self.storage / 'transactions' / previous['transaction']
            journal = json.loads((transaction / 'journal.json').read_text())
            self._restore(transaction, journal)
            self._write_sha(previous['sha'])
            value.update(previous=None, available=None, staged=None, message='Previous application restored. Your saved work was retained.')
        else:
            sha = state['staged']['sha']
            stage, manifest = self._stage(sha)
            transaction = regular_folder(self.storage / 'transactions' / uuid.uuid4().hex)
            journal = {'version': 1, 'status': 'applying', 'before_sha': state['current'], 'after_sha': sha, 'operations': []}
            atomic_json(transaction / 'journal.json', journal)
            try:
                for name, record in manifest['files'].items():
                    target = self.destination(name)
                    before = file_hash(target)
                    if before == record['sha256']:
                        continue
                    if before is not None:
                        backup = transaction / 'files' / archive_path(name)
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, backup)
                    operation = {'path': name, 'before': before, 'after': record['sha256']}
                    journal['operations'].append(operation)
                    atomic_json(transaction / 'journal.json', journal)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_name(target.name + '.update-' + uuid.uuid4().hex)
                    try:
                        shutil.copyfile(stage / 'files' / archive_path(name), temporary)
                        temporary.chmod(record['mode'])
                        if file_hash(target) != before:
                            raise ValueError('An application file changed while the update was being installed.')
                        os.replace(temporary, target)
                    finally:
                        temporary.unlink(missing_ok=True)
                self._write_sha(sha)
                # The durable receipt precedes completion. If interrupted here,
                # recover() restores both files and the matching saved state.
                value.update(previous={'sha': state['current'], 'transaction': transaction.name}, staged=None, available=None,
                             message='Application updated. Your saved work was retained.')
                atomic_json(self.file, value)
                journal['status'] = 'complete'
                atomic_json(transaction / 'journal.json', journal)
            except BaseException:
                self._restore(transaction, journal)
                self._write_sha(journal['before_sha'])
                journal['status'] = 'recovered'
                atomic_json(transaction / 'journal.json', journal)
                atomic_json(self.file, before_state)
                raise
            value.update(previous={'sha': state['current'], 'transaction': transaction.name}, staged=None, available=None,
                         message='Application updated. Your saved work was retained.')
        atomic_json(self.file, value)
        pending_file.unlink()
        return self.state()
