"""Bootstrap boundaries tested without network, system installs or a GUI."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from desktop.bootstrap import (download, extract_zip, platform_key, resolve_workspace,
                               restore_engines, retire_legacy_files, verify_renderer)
from tests.desktop_install_fixtures import application, write


class SetupSafetyTests(unittest.TestCase):
    def test_verified_downloads_offline_cache_and_safe_extraction(self):
        payload = b'verified fixture'
        spec = {'url': 'https://example.invalid/runtime.zip', 'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)}
        class Response(io.BytesIO):
            def geturl(self): return spec['url']
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch('desktop.bootstrap.urllib.request.urlopen', return_value=Response(payload)) as fetch:
                cached = download(spec, root)
                self.assertEqual(cached.read_bytes(), payload)
                self.assertEqual(download(spec, root, offline=True), cached)
                fetch.assert_called_once()
            cached.write_bytes(b'corrupt')
            with patch('desktop.bootstrap.urllib.request.urlopen') as fetch:
                with self.assertRaisesRegex(ValueError, 'not cached'):
                    download(spec, root, offline=True)
                fetch.assert_not_called()
            with patch('desktop.bootstrap.urllib.request.urlopen', return_value=Response(b'wrong')):
                with self.assertRaisesRegex(ValueError, 'verification failed'):
                    download(spec, root)
            self.assertFalse(list((root / 'downloads').glob('*.part')))
            archive = root / 'bad.zip'
            for index, name in enumerate(('../escape', '/escape', 'C:/escape', 'a\\escape')):
                with self.subTest(path=name), zipfile.ZipFile(archive, 'w') as output:
                    output.writestr(name, 'outside')
                with self.assertRaisesRegex(ValueError, 'unsafe path'):
                    extract_zip(archive, root / str(index))
            self.assertFalse((root / 'escape').exists())
            with zipfile.ZipFile(archive, 'w') as output:
                file = zipfile.ZipInfo('bin/runtime')
                file.external_attr = (stat.S_IFREG | 0o755) << 16
                output.writestr(file, b'#!/bin/sh\nexit 0\n')
                link = zipfile.ZipInfo('outside')
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                output.writestr(link, '../escape')
            with self.assertRaisesRegex(ValueError, 'link leaves'):
                extract_zip(archive, root / 'links', allow_links=True)
            if os.name != 'nt':
                self.assertTrue((root / 'links/bin/runtime').stat().st_mode & 0o111)

    def test_engine_restore_verifies_before_writing_and_preserves_backups(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = application(Path(temporary) / 'app')
            backup = Path(temporary) / 'backup'
            write(backup, 'snapshot.json', '{"legacy": true}')
            original = write(root, 'modules/csv.py', 'SOURCE_COLUMN = 8\n')
            restore_engines(root, backup)
            saved = list((backup / 'engine-code').glob('csv-*.py'))
            self.assertEqual(saved[0].read_text(), 'SOURCE_COLUMN = 8\n')
            original.write_text('SOURCE_COLUMN = 9\n')
            restore_engines(root, backup)
            self.assertEqual(original.read_text(), 'SOURCE_COLUMN = 9\n')
            write(root, 'desktop/engine-defaults/wolf.py', 'changed')
            before = {p.name: p.read_bytes() for p in (root / 'modules').iterdir()}
            with self.assertRaisesRegex(ValueError, 'verified default'):
                restore_engines(root, backup)
            self.assertEqual({p.name: p.read_bytes() for p in (root / 'modules').iterdir()}, before)
            verify_renderer(root)
            write(root, 'desktop/dist/index.html', 'tampered')
            with self.assertRaisesRegex(ValueError, 'incomplete or changed'):
                verify_renderer(root)
            retired = write(root, 'gui/config_tab.py', 'old Qt code with a local customization')
            retire_legacy_files(root, backup)
            self.assertFalse(retired.exists())
            self.assertEqual(next((backup / 'retired-files/gui').glob('config_tab-*.py')).read_text(), 'old Qt code with a local customization')

    def test_workspace_binding_retains_saved_work_and_the_spending_ledger(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'DAZEDTL_DESKTOP_WORKSPACE': ''}):
            root, profile = Path(temporary) / 'app', Path(temporary) / 'profile'
            previous = write(root, '.tmp-ui/desktop-workspace/spend.sqlite3', b'existing ledger').parent
            self.assertEqual(resolve_workspace(root, profile), previous)
            self.assertEqual(resolve_workspace(Path(temporary) / 'relocated-app', profile), previous)
            self.assertEqual((previous / 'spend.sqlite3').read_bytes(), b'existing ledger')
            with patch.dict(os.environ, {'DAZEDTL_DESKTOP_WORKSPACE': str(Path(temporary) / 'explicit')}):
                self.assertEqual(resolve_workspace(root, profile), Path(temporary) / 'explicit')
            self.assertEqual(platform_key('win32', 'AMD64'), 'win32_x64')
            self.assertEqual(platform_key('win32', 'ARM64'), 'win32_x64')
            self.assertEqual(platform_key('darwin', 'arm64'), 'darwin_arm64')
            with self.assertRaisesRegex(ValueError, '64-bit'):
                platform_key('linux', 'i686')
