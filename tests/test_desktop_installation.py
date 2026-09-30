"""Fresh-install, legacy-upgrade and transactional-update external contracts."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from desktop.bootstrap import restore_engines, retire_legacy_files
from desktop.backend.migration import capture, apply
from desktop.backend.settings import SettingsStore
from desktop.source_updates import SourceInstallation
from tests.desktop_install_fixtures import ENGINES, application, source_zip, write
from util.api_keys import load_vault, save_vault

REPO = Path(__file__).resolve().parents[1]


class DesktopInstallationTests(unittest.TestCase):
    def test_old_qt_archive_update_preserves_settings_and_reaches_electron(self):
        from tests.fixtures import legacy_qt_updater as legacy
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            incoming = application(base / 'incoming')
            old = base / 'Previous install 日本語'
            workspace = base / 'new profile'
            for name, data in ENGINES.items():
                write(incoming, 'modules/' + name, data)
                write(old, 'modules/' + name, data)
            write(old, 'modules/csv.py', 'SOURCE_COLUMN = 5\nTARGET_COLUMN = 7\nCSV_DELIMITER = ";"\n')
            original_env = write(old, '.env', 'language=French\nwidth=74\nmistralReqPerMin=12\nmistralTokPerMin=9000\nwolfDbIncludeTiers=\'["foundation"]\'\n').read_bytes()
            save_vault({'active': 'Old account', 'keys': {'Old account': {'secret': 'old-fixture-only', 'endpoint': 'https://provider.example.invalid/v1', 'keyless': False}}}, old / 'data/api_keys.json')
            original_vault = (old / 'data/api_keys.json').read_bytes()
            for name in ('files/input.json', 'translated/result.json', 'log/saved-job.json'):
                write(old, name, 'user data')
                write(incoming, name, 'must never replace user data')
            write(incoming, '.env', 'language=Wrong\n')
            write(incoming, 'data/api_keys.json', '{"keys":{}}')
            write(old, 'gui/config_tab.py', 'retired locally customized Qt code')
            for name in ('gui/main.py', 'scripts/start_gui.py'):
                write(incoming, name, (REPO / name).read_bytes())
            write(incoming, '.gitattributes', (REPO / '.gitattributes').read_bytes())
            write(incoming, '.git_archival.txt', 'node: $Format:%H$\n')
            environment = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}
            def git(*args):
                return subprocess.check_output(['git', '-C', str(incoming), *args], env=environment, stderr=subprocess.PIPE)
            git('init', '-q'); git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
            sha = git('rev-parse', 'HEAD').decode().strip()
            archive = base / 'update.zip'
            archive.write_bytes(git('archive', '--format=zip', '--prefix=dazedtl/', 'HEAD'))
            worker = legacy.LegacyQtUpdater()
            worker._download_archive = lambda destination, _: shutil.copyfile(archive, destination)
            with patch.object(legacy, 'PROJECT_ROOT', old), patch.object(worker, 'SHA_FILE', str(old / 'data/last_update_sha.txt')):
                worker._download_and_apply(legacy.UpdateCandidate(sha, worker.UPDATE_SOURCES[1]))
            self.assertEqual((old / '.env').read_bytes(), original_env)
            self.assertEqual((old / 'data/api_keys.json').read_bytes(), original_vault)
            self.assertIn('SOURCE_COLUMN = 5', (old / 'modules/csv.py').read_text())
            for name in ('files/input.json', 'translated/result.json', 'log/saved-job.json'):
                self.assertEqual((old / name).read_text(), 'user data')
            game = base / 'Game'; game.mkdir()
            snapshot = capture(old, workspace, preferences={'workflow/last_game_folder': str(game)})
            restore_engines(old, Path(snapshot['backup']))
            # A failed first launch may have refreshed code before the old app
            # finishes saving preferences. Retrying keeps embedded options.
            write(old, '.env', original_env + b'listWidth=88\n')
            capture(old, workspace, preferences={})
            report = apply(old, workspace)
            retire_legacy_files(old, Path(snapshot['backup']))
            saved = SettingsStore(workspace, code_root=old).read()
            self.assertEqual(saved['values']['language'], 'French')
            self.assertEqual(saved['values']['listWidth'], 88)
            self.assertEqual(saved['values']['mistralReqPerSec'], 0.2)
            self.assertEqual(saved['values']['mistralTokPerMin'], 9000)
            self.assertEqual(json.loads(saved['values']['wolfDbIncludeTiers']), ['foundation'])
            self.assertEqual(saved['engines']['csv']['SOURCE_COLUMN'], 5)
            self.assertEqual(saved['engines']['csv']['TARGET_COLUMN'], 7)
            self.assertEqual(load_vault(workspace / 'settings/api_keys.json')['keys']['Old account']['secret'], 'old-fixture-only')
            self.assertEqual((old / 'modules/csv.py').read_text(), ENGINES['csv.py'])
            self.assertFalse((old / 'gui/config_tab.py').exists())
            self.assertTrue(list((Path(snapshot['backup']) / 'retired-files/gui').glob('config_tab-*.py')))
            self.assertEqual(report['recent'][0]['source'], str(game))
            self.assertEqual(apply(old, workspace), report)
            self.assertEqual((old / '.env').read_bytes(), original_env + b'listWidth=88\n')
            # An existing shortcut still calls start_gui.py after Qt updates.
            result = subprocess.run([sys.executable, '-I', '-B', str(old / 'scripts/start_gui.py')],
                                    cwd=base, env=environment, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('ELECTRON_BOOTSTRAP_REACHED', result.stdout)

    def test_credential_collisions_cannot_rebind_or_resume_a_paid_job_silently(self):
        from desktop.backend.batches import Batches, run_action
        from desktop.backend.manual import ManualJobs
        from util import api_keys
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = application(base / 'old')
            workspace = base / 'workspace'
            for name, data in ENGINES.items(): write(source, 'modules/' + name, data)
            write(source, '.env', 'language=French\nmistralReqPerSec=0.2\n')
            old_key = {'secret': 'OLD-fixture-value', 'endpoint': 'https://provider.example.invalid/v1', 'keyless': False}
            new_key = {**old_key, 'secret': 'NEW-fixture-value'}
            save_vault({'active': 'Shared name', 'keys': {'Shared name': old_key}}, source / 'data/api_keys.json')
            store = SettingsStore(workspace, code_root=source)
            store.save(0, {**store.read()['values'], 'language': 'German'}, {})
            saved = json.loads(store.path.read_text())
            del saved['values']['mistralReqPerSec']
            store.path.write_text(json.dumps(saved))
            save_vault({'active': 'Shared name', 'keys': {'Shared name': new_key}}, store.vault_path)
            row = {'id': 'batch-fixture', 'key_name': 'Shared name', 'endpoint': old_key['endpoint'],
                   'provider': 'openai', 'model': 'fixture', 'status': 'submitted', 'workflow': 'translation'}
            history_path = write(source, 'log/batch_history.json', json.dumps({'version': 1, 'batches': [row]}))
            previous = history_path.read_bytes()
            snapshot = capture(source, workspace, preferences={})
            restore_engines(source, Path(snapshot['backup']))
            report = apply(source, workspace)
            self.assertEqual(store.read()['values']['language'], 'German')
            self.assertEqual(store.read()['values']['mistralReqPerSec'], 0.2)
            self.assertEqual(load_vault(store.vault_path)['keys']['Shared name'], new_key)
            alias = report['credential_aliases']['Shared name']
            self.assertEqual(load_vault(store.vault_path)['keys'][alias], old_key)
            self.assertEqual(history_path.read_bytes(), previous)
            operations = SimpleNamespace(active=None, jobs={}, running=lambda: False, start=Mock(return_value={'id': 'operation'}))
            batches = Batches(workspace, operations, ManualJobs(workspace, threading.RLock()), allow_providers=True)
            public = batches.state()
            selected = public['rows'][0]
            self.assertEqual(selected['key_name'], '')
            self.assertNotIn(old_key['secret'], json.dumps(public))
            self.assertNotIn(new_key['secret'], json.dumps(public))
            with self.assertRaisesRegex(ValueError, 'imported Qt credential'):
                batches.action(selected['source_id'], row['id'], 'refresh')
            with self.assertRaisesRegex(ValueError, 'imported Qt credential'):
                batches.action(selected['source_id'], row['id'], 'bind', key_name='Shared name', revision=selected['revision'])
            operations.start.assert_not_called()
            batches.action(selected['source_id'], row['id'], 'bind', key_name=alias, revision=selected['revision'])
            plan = operations.start.call_args.args[0]
            self.assertEqual(plan['rebind_from'], 'Shared name')
            original_cwd = Path.cwd()
            try:
                with patch.dict(os.environ, dict(os.environ)), patch.object(api_keys, 'API_KEYS_PATH', store.vault_path), \
                     patch.object(socket, 'create_connection'), patch.object(socket.socket, 'connect'), patch.object(socket.socket, 'connect_ex'):
                    run_action(plan, lambda _: None)
            finally:
                os.chdir(original_cwd)
            self.assertEqual(json.loads(history_path.read_text())['batches'][0]['key_name'], alias)
            # An older .env-only key belongs to its old endpoint, even when
            # the existing desktop profile uses another provider.
            env_only = application(base / 'env-only')
            write(env_only, '.env', 'key=old-env-fixture\napi=http://127.0.0.1:9\n')
            for name, data in ENGINES.items(): write(env_only, 'modules/' + name, data)
            capture(env_only, workspace, preferences={})
            apply(env_only, workspace)
            self.assertEqual(load_vault(store.vault_path)['keys']['Imported']['endpoint'], 'http://127.0.0.1:9')

    def test_source_update_staging_rollback_and_interrupted_apply_preserve_user_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = application(base / 'incoming')
            root = application(base / 'installed', version='old')
            write(root, 'data/last_update_sha.txt', 'a' * 40)
            write(root, '.env', 'private preferences')
            write(root, 'files/input.json', 'original input')
            write(source, '.env', 'must not install')
            write(source, 'files/input.json', 'must not install')
            archive = source_zip(source, base / 'new.zip')
            installer = SourceInstallation(root, base / 'profile')
            original = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            staged = installer.stage_archive(archive, 'b' * 40, prepare_runtimes=False)
            staged_index = installer.storage / 'staged' / ('b' * 40) / 'files/desktop/dist/index.html'
            staged_index.write_text('modified after download')
            with self.assertRaisesRegex(ValueError, 'staged update changed'):
                installer.schedule('activate', staged['revision'])
            staged = installer.stage_archive(archive, 'b' * 40, prepare_runtimes=False)
            installer.schedule('activate', staged['revision'])
            updated = installer.apply_pending()
            self.assertEqual(updated['current'], 'b' * 40)
            self.assertEqual((root / '.env').read_text(), 'private preferences')
            self.assertEqual((root / 'files/input.json').read_text(), 'original input')
            changed = root / 'desktop/electron/main.cjs'
            expected = changed.read_bytes()
            changed.write_text('newer user edit')
            before_rollback = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            installer.schedule('rollback', updated['revision'])
            with self.assertRaisesRegex(ValueError, 'changed after update'):
                installer.apply_pending()
            self.assertEqual({p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}, before_rollback)
            changed.write_bytes(expected)
            restored = installer.apply_pending()
            self.assertEqual(restored['current'], 'a' * 40)
            self.assertEqual({p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}, original)
            staged = installer.stage_archive(archive, 'b' * 40, prepare_runtimes=False)
            installer.schedule('activate', staged['revision'])
            replace = os.replace
            tripped = False
            def interrupted(src, dst):
                nonlocal tripped
                if Path(dst) == changed and not tripped:
                    tripped = True
                    raise OSError('simulated interrupted copy')
                return replace(src, dst)
            with patch('desktop.source_updates.os.replace', side_effect=interrupted), self.assertRaisesRegex(OSError, 'interrupted copy'):
                installer.apply_pending()
            self.assertEqual({p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}, original)
            self.assertEqual(installer.installed_sha(), 'a' * 40)
            # Power loss after saving the active receipt but before completing
            # its journal must reconcile the saved selection as well as files.
            state = installer.state()
            installer.schedule('activate', state['revision'])
            updated = installer.apply_pending()
            journal_file = installer.storage / 'transactions' / updated['previous']['transaction'] / 'journal.json'
            journal = json.loads(journal_file.read_text())
            journal['status'] = 'applying'
            journal_file.write_text(json.dumps(journal))
            installer.recover()
            recovered = installer.state()
            self.assertEqual(recovered['current'], 'a' * 40)
            self.assertIsNone(recovered['previous'])
            self.assertEqual(recovered['staged']['sha'], 'b' * 40)
            self.assertEqual({p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}, original)

    @unittest.skipUnless(shutil.which('bash') and os.name != 'nt', 'POSIX bootstrap entry point')
    def test_one_click_shell_bootstraps_without_python_or_node_on_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / 'Fresh install 日本語'
            commands = base / 'commands'; commands.mkdir()
            for name in ('bash', 'dirname', 'awk', 'mkdir', 'mktemp', 'tar', 'gzip', 'find', 'cp', 'chmod', 'sha256sum', 'rm'):
                found = shutil.which(name)
                if not found: self.skipTest(name + ' is unavailable')
                (commands / name).symlink_to(found)
            uname = write(commands, 'uname', '#!/bin/sh\nif [ "$1" = -s ]; then echo Linux; else echo x86_64; fi\n'); uname.chmod(0o755)
            uv = ('#!/bin/sh\ncase "$*" in *"python find"*) printf "%s\\n" ' + shlex.quote(sys.executable) + ';; *) exit 0;; esac\n').encode()
            archive = base / 'runtime.tar.gz'
            with tarfile.open(archive, 'w:gz') as target:
                member = tarfile.TarInfo('uv-fixture/uv'); member.size = len(uv); member.mode = 0o755
                target.addfile(member, io.BytesIO(uv))
            curl = write(commands, 'curl', '#!/bin/sh\nwhile [ "$1" != --output ]; do shift; done\nshift\n' + shlex.quote(shutil.which('cp')) + ' ' + shlex.quote(str(archive)) + ' "$1"\n'); curl.chmod(0o755)
            for name in ('START.sh', 'scripts/setup_desktop.sh'):
                write(root, name, (REPO / name).read_bytes())
            receipt = root / 'started.json'
            write(root, 'scripts/setup_desktop.py', 'from pathlib import Path\nPath(' + repr(str(receipt)) + ').write_text("managed Python reached the desktop bootstrap")\n')
            manifest = {'uv_version': 'fixture', 'python_version': '3.12.14', 'uv_linux_x64_url': 'https://example.invalid/uv.tar.gz', 'uv_linux_x64_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}
            for accepted in (True, False):
                with self.subTest(valid_hash=accepted):
                    receipt.unlink(missing_ok=True)
                    if not accepted: manifest['uv_linux_x64_sha256'] = '0' * 64
                    write(root, 'desktop/setup-runtimes.json', json.dumps(manifest, indent=2))
                    env = {**os.environ, 'PATH': str(commands), 'DAZEDTL_SETUP_HOME': str(base / str(accepted))}
                    result = subprocess.run([shutil.which('bash'), str(root / 'START.sh'), '--setup-only'], env=env, cwd=base,
                                            capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode == 0, accepted, result.stdout + result.stderr)
                    self.assertEqual(receipt.exists(), accepted)
                    if accepted:
                        # An interrupted copy must be retried before attempting
                        # to execute an incomplete cached setup tool.
                        installed = base / str(accepted) / 'shell-uv-fixture-linux_x64'
                        (installed / 'verified.json').unlink()
                        (installed / 'uv').write_text('#!/bin/sh\nexit 9\n')
                        receipt.unlink()
                        retry = subprocess.run([shutil.which('bash'), str(root / 'START.sh'), '--setup-only'],
                                               env=env, cwd=base, capture_output=True, text=True, timeout=5)
                        self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
                        self.assertTrue(receipt.exists())
