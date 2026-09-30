#!/usr/bin/env python3
"""Private process boundary for one-click application updates."""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.source_updates import SourceInstallation


def wait_for_parent(pid):
    if pid <= 0 or pid == os.getpid():
        raise ValueError('Invalid previous application process.')
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if handle:
            try:
                if kernel.WaitForSingleObject(ctypes.c_void_p(handle), 90000) != 0:
                    raise TimeoutError('The previous application is still open. Its files were not changed.')
            finally:
                kernel.CloseHandle(ctypes.c_void_p(handle))
    else:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        raise TimeoutError('The previous application is still open. Its files were not changed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('state', 'check', 'download', 'schedule', 'apply'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--choice', choices=('activate', 'rollback'))
    parser.add_argument('--revision', default='')
    parser.add_argument('--wait-pid', type=int)
    args = parser.parse_args()
    installer = SourceInstallation(args.root, args.profile)
    with redirect_stdout(sys.stderr):
        if args.action == 'schedule':
            result = installer.schedule(args.choice, args.revision)
        elif args.action == 'apply':
            if args.wait_pid:
                wait_for_parent(args.wait_pid)
            try:
                result = installer.apply_pending()
            except Exception as error:
                from desktop.bootstrap import atomic_json
                state = installer._read()
                state['message'] = f'The update could not finish: {error}. Existing work was retained.'
                atomic_json(installer.file, state)
                unresolved = any(json.loads(file.read_text()).get('status') == 'applying'
                                 for file in (installer.storage / 'transactions').glob('*/journal.json'))
                if unresolved:
                    raise
                (installer.storage / 'pending.json').unlink(missing_ok=True)
                result = installer.state()
            environment = dict(os.environ)
            environment['DAZEDTL_DESKTOP_PROFILE'] = str(args.profile)
            subprocess.run([sys.executable, '-I', '-B', str(args.root / 'scripts/setup_desktop.py')], env=environment, check=True)
        else:
            result = getattr(installer, args.action)()
    print(json.dumps(result))


if __name__ == '__main__':
    main()
