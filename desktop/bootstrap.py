"""One-click, per-user desktop setup. The bootstrap itself uses only the stdlib."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import uuid
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ENGINE_FILES = frozenset({'rpgmakermvmz.py', 'csv.py', 'wolf.py', 'srpg.py'})


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.setup-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def platform_key(system=None, machine=None):
    system = system or sys.platform
    machine = (machine or platform.machine()).lower()
    arch = {'x86_64': 'x64', 'amd64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(machine)
    if system not in {'linux', 'darwin', 'win32'} or not arch:
        raise ValueError('DazedTL requires 64-bit Windows, macOS or desktop Linux.')
    # The locked OpenCV wheel is x64-only on Windows. Windows on ARM runs
    # the matching x64 Python and Electron through its built-in emulation.
    if system == 'win32':
        arch = 'x64'
    return system + '_' + arch


def setup_home():
    explicit = os.getenv('DAZEDTL_SETUP_HOME')
    if explicit:
        return Path(explicit).expanduser().resolve()
    if sys.platform == 'win32':
        base = Path(os.getenv('LOCALAPPDATA', Path.home() / 'AppData/Local'))
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library/Caches'
    else:
        base = Path(os.getenv('XDG_CACHE_HOME', Path.home() / '.cache'))
    return base / 'DazedTL/setup'


def profile_home():
    explicit = os.getenv('DAZEDTL_DESKTOP_PROFILE')
    if explicit:
        return Path(explicit).expanduser().resolve()
    if sys.platform == 'win32':
        base = Path(os.getenv('APPDATA', Path.home() / 'AppData/Roaming'))
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library/Application Support'
    else:
        base = Path(os.getenv('XDG_CONFIG_HOME', Path.home() / '.config'))
    return base / 'DazedTL'


def regular_folder(path):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        if parent.is_symlink() or getattr(parent, 'is_junction', lambda: False)():
            raise ValueError('Setup storage must not contain symbolic links or directory junctions.')
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def setup_lock(cache, timeout=300):
    """An OS-held lock is released even when setup is interrupted."""
    path = regular_folder(cache) / 'setup.lock'
    with path.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        deadline = time.monotonic() + timeout
        waiting = False
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Another DazedTL setup is still running. Let it finish, then try again.')
                if not waiting:
                    print('Waiting for the other setup to finish…', flush=True)
                    waiting = True
                time.sleep(0.2)
        try:
            yield
        finally:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_UN)


def archive_path(name):
    value = PurePosixPath(name)
    if not name or '\\' in name or ':' in name or value.is_absolute() or any(p in {'', '.', '..'} for p in name.split('/')):
        raise ValueError('The downloaded archive contains an unsafe path.')
    return Path(*value.parts)


def filesystem_path(path):
    """Permit deep bundled skill paths on Windows without changing metadata."""
    path = Path(path).absolute()
    value = str(path)
    if os.name == 'nt' and not value.startswith('\\\\?\\'):
        return Path('\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value)
    return path


def extract_zip(archive, target, *, allow_links=False):
    """Restore Electron's executable modes and internal macOS framework links."""
    root = regular_folder(filesystem_path(target)).resolve()
    links = []
    with zipfile.ZipFile(archive) as source:
        if sum(item.file_size for item in source.infolist()) > 2 * 1024**3:
            raise ValueError('The downloaded runtime expands beyond its size limit.')
        for item in source.infolist():
            relative = archive_path(item.filename.rstrip('/'))
            destination = root / relative
            if not destination.resolve().is_relative_to(root):
                raise ValueError('The downloaded archive leaves its destination.')
            mode = item.external_attr >> 16
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            elif stat.S_ISLNK(mode):
                if not allow_links or item.file_size > 4096:
                    raise ValueError('Unexpected symbolic link in a runtime archive.')
                links.append((destination, source.read(item).decode('utf-8')))
            elif stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                raise ValueError('Unexpected special file in a runtime archive.')
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.open(item) as incoming, destination.open('xb') as output:
                    shutil.copyfileobj(incoming, output)
                destination.chmod((mode & 0o777) or 0o644)
    for destination, link in links:
        if Path(link).is_absolute() or '\\' in link or ':' in link or not (destination.parent / link).resolve().is_relative_to(root):
            raise ValueError('A runtime link leaves the downloaded application.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(link)
    for destination, _ in links:
        if not destination.resolve().is_relative_to(root):
            raise ValueError('A runtime link chain leaves the application.')


def download(spec, cache, *, offline=False):
    url, sha = spec['url'], spec['sha256']
    if not url.startswith('https://') or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
        raise ValueError('Invalid pinned runtime download metadata.')
    name = url.rsplit('/', 1)[1]
    relative = archive_path(name)
    target = regular_folder(cache / 'downloads') / (sha[:16] + '-' + relative.name)
    if target.is_file() and not target.is_symlink() and digest(target) == sha:
        return target
    if offline:
        raise ValueError(f'{name} is not cached. Connect once to finish setup.')
    temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.part')
    print(f'Downloading {name}…', flush=True)
    limit = spec.get('bytes', 512 * 1024**2)
    if type(limit) is not int or not 0 < limit <= 512 * 1024**2:
        raise ValueError('Invalid runtime download size.')
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'DazedTL-Setup'})
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open('xb') as output:
            if not response.geturl().startswith('https://'):
                raise ValueError('Runtime download redirected to an insecure connection.')
            received, last_percent = 0, -1
            while chunk := response.read(1024**2):
                received += len(chunk)
                if received > limit:
                    raise ValueError('Runtime download exceeded its expected size.')
                output.write(chunk)
                percent = int(received * 10 / limit) * 10
                if percent != last_percent:
                    print(f'  {percent}% ({received // 1024**2} MB)', flush=True)
                    last_percent = percent
        if digest(temporary) != sha or 'bytes' in spec and received != spec['bytes']:
            raise ValueError('Runtime verification failed. The downloaded file was not installed.')
        os.replace(temporary, target)
        return target
    finally:
        temporary.unlink(missing_ok=True)


def artifact(config, component, key):
    prefix = component + '_' + key
    return {part: config[prefix + '_' + part] for part in ('url', 'sha256', 'bytes')}


def ensure_uv(config, cache, key, offline=False):
    spec = artifact(config, 'uv', key)
    folder = cache / ('uv-' + config['uv_version'] + '-' + key)
    executable = folder / ('uv.exe' if key.startswith('win32') else 'uv')
    marker = folder / 'verified.json'
    if executable.is_file() and marker.is_file() and json.loads(marker.read_text()).get('archive') == spec['sha256']:
        return executable
    shell_folder = cache / ('shell-uv-' + config['uv_version'] + '-' + key)
    shell_executable = shell_folder / executable.name
    shell_marker = shell_folder / 'verified.json'
    if shell_executable.is_file() and shell_marker.is_file() and json.loads(shell_marker.read_text()).get('archive') == spec['sha256']:
        return shell_executable
    archive = download(spec, cache, offline=offline)
    with tempfile.TemporaryDirectory(prefix='uv-', dir=cache) as temporary:
        temporary = Path(temporary)
        if archive.suffix == '.zip':
            extract_zip(archive, temporary)
        else:
            with tarfile.open(archive) as source:
                source.extractall(temporary, filter='data')
        matches = [p for p in temporary.rglob(executable.name) if p.is_file() and not p.is_symlink()]
        if len(matches) != 1:
            raise ValueError('The verified uv runtime did not contain its executable.')
        regular_folder(folder)
        shutil.copy2(matches[0], executable)
        executable.chmod(0o755)
        atomic_json(marker, {'archive': spec['sha256']})
    return executable


def run(command, *, env, capture=False, timeout=900):
    result = subprocess.run([str(part) for part in command], env=env, check=True, timeout=timeout,
                            stdout=subprocess.PIPE if capture else None,
                            text=capture, encoding='utf-8' if capture else None,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return result.stdout.strip() if capture else None


def clean_environment(cache):
    env = dict(os.environ)
    for key in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'UV_INDEX', 'UV_INDEX_URL', 'UV_EXTRA_INDEX_URL',
                'UV_DEFAULT_INDEX', 'UV_CONFIG_FILE', 'PIP_INDEX_URL', 'PIP_EXTRA_INDEX_URL'):
        env.pop(key, None)
    env.update(UV_PYTHON_INSTALL_DIR=str(cache / 'pythons'), UV_CACHE_DIR=str(cache / 'uv-cache'),
               UV_NO_CONFIG='1', PYTHONNOUSERSITE='1', PYTHON_DOTENV_DISABLED='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    return env


def ensure_python(root, config, cache, uv, key, *, offline=False):
    env = clean_environment(cache)
    command = [uv, '--no-config', *(['--offline'] if offline else [])]
    version = config['python_version']
    request = f'cpython-{version}-windows-x86_64-none' if key.startswith('win32') else version
    run([*command, 'python', 'install', request, '--no-bin', '--no-registry'], env=env)
    base_python = run([*command, 'python', 'find', '--managed-python', '--no-project', request], env=env, capture=True)
    lock = root / 'desktop/requirements-runtime.lock'
    fingerprint = hashlib.sha256(lock.read_bytes() + version.encode()).hexdigest()
    target = cache / ('python-env-' + key + '-' + fingerprint[:16])
    python = target / ('Scripts/python.exe' if key.startswith('win32') else 'bin/python')
    marker = target / '.dazedtl-environment.json'
    if python.is_file() and marker.is_file() and json.loads(marker.read_text()).get('requirements') == fingerprint:
        return python
    print('Installing the locked Python dependencies…', flush=True)
    regular_folder(target)
    run([base_python, '-I', '-m', 'venv', '--without-pip', target], env=env)
    run([*command, 'pip', 'sync', '--python', python, '--require-hashes', '--only-binary', ':all:',
         '--index-url', 'https://pypi.org/simple', lock], env=env)
    atomic_json(marker, {'requirements': fingerprint, 'python': version})
    return python


def ensure_electron(config, cache, key, *, offline=False):
    spec = artifact(config, 'electron', key)
    folder = cache / ('electron-' + config['electron_version'] + '-' + key)
    executable = folder / ('electron.exe' if key.startswith('win32') else 'Electron.app/Contents/MacOS/Electron' if key.startswith('darwin') else 'electron')
    marker = folder / '.dazedtl-runtime.json'
    if executable.is_file() and marker.is_file() and json.loads(marker.read_text()).get('archive') == spec['sha256']:
        return executable
    archive = download(spec, cache, offline=offline)
    with tempfile.TemporaryDirectory(prefix='electron-', dir=cache) as temporary:
        temporary = Path(temporary)
        extract_zip(archive, temporary, allow_links=key.startswith('darwin'))
        candidate = temporary / executable.relative_to(folder)
        if not candidate.is_file():
            raise ValueError('The verified Electron archive is incomplete.')
        candidate.chmod(0o755)
        if folder.exists():
            regular_folder(folder)
            shutil.rmtree(folder)
        shutil.copytree(temporary, folder, symlinks=True)
        atomic_json(marker, {'archive': spec['sha256']})
    return executable


def verify_renderer(root):
    folder = root / 'desktop/dist'
    marker = folder / 'renderer-manifest.json'
    if not marker.is_file():
        raise ValueError('This download is missing its built interface. Extract the complete DazedTL archive.')
    manifest = json.loads(marker.read_text())
    if manifest.get('version') != 1 or 'index.html' not in manifest.get('files', {}):
        raise ValueError('The built interface manifest is invalid.')
    for name, expected in manifest['files'].items():
        file = folder / archive_path(name)
        if file.is_symlink() or not file.is_file() or digest(file) != expected:
            raise ValueError('The built interface is incomplete or changed. Re-extract the complete application.')


def verify_engines(root):
    folder = root / 'desktop/engine-defaults'
    manifest = json.loads((folder / 'manifest.json').read_text())
    if manifest.get('version') != 1 or set(manifest.get('files', {})) != ENGINE_FILES:
        raise ValueError('The shipped engine defaults are incomplete.')
    for name, expected in manifest['files'].items():
        source = folder / name
        if source.is_symlink() or not source.is_file() or digest(source) != expected:
            raise ValueError('A shipped engine did not match its verified default.')
    return manifest


def restore_engines(root, backup):
    folder = root / 'desktop/engine-defaults'
    manifest = verify_engines(root)
    installed = backup / 'engine-install.json'
    previous = json.loads(installed.read_text()).get('files', {}) if installed.is_file() else {}
    snapshot = backup / 'snapshot.json'
    legacy = json.loads(snapshot.read_text()).get('legacy', False) if snapshot.is_file() else False
    for name, expected in manifest['files'].items():
        current = root / 'modules' / name
        while current != root:
            if current.is_symlink() or getattr(current, 'is_junction', lambda: False)():
                raise ValueError('Engine installation cannot write through links or junctions.')
            current = current.parent
    for name, expected in manifest['files'].items():
        target = root / 'modules' / name
        if target.is_symlink():
            raise ValueError('Engine files must not be symbolic links.')
        if target.is_file() and digest(target) == expected:
            continue
        if target.is_file() and (previous.get(name) == expected or (root / '.git').exists() and not legacy and not previous):
            # Keep a developer's changes when the shipped engine did not change.
            continue
        if target.exists():
            saved = regular_folder(backup / 'engine-code') / (target.stem + '-' + digest(target)[:16] + '.py')
            if not saved.exists():
                shutil.copy2(target, saved)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.setup-' + uuid.uuid4().hex)
        try:
            shutil.copy2(folder / name, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    atomic_json(installed, {'version': 1, 'files': manifest['files']})


def resolve_workspace(root, profile):
    explicit = os.getenv('DAZEDTL_DESKTOP_WORKSPACE')
    if explicit:
        return Path(explicit).expanduser().resolve()
    binding = profile / 'workspace.json'
    if binding.is_file():
        return Path(json.loads(binding.read_text())['path']).expanduser().resolve()
    previous = root / '.tmp-ui/desktop-workspace'
    workspace = previous if (previous / 'spend.sqlite3').is_file() or (previous / 'projects').is_dir() else profile / 'workspace'
    atomic_json(binding, {'version': 1, 'path': str(workspace.resolve())})
    return workspace


def retire_legacy_files(root, backup):
    manifest = json.loads((root / 'desktop/retired-qt-files.json').read_text())
    if manifest.get('version') != 1 or not isinstance(manifest.get('files'), list):
        raise ValueError('The legacy cleanup manifest is invalid.')
    for name in manifest['files']:
        relative = archive_path(name)
        if relative.suffix != '.py' or relative.parts[0] not in {'gui', 'scripts', 'tests', 'util'} or name in {'gui/main.py', 'gui/__init__.py', 'scripts/start_gui.py'}:
            raise ValueError('Legacy cleanup attempted to touch a protected path.')
        original = root / relative
        if not original.exists():
            continue
        if original.is_symlink() or not original.resolve().is_relative_to(root) or not original.is_file():
            raise ValueError('Legacy code cleanup cannot follow links or remove directories.')
        expected = digest(original)
        target = backup / 'retired-files' / relative.parent / (relative.stem + '-' + expected[:16] + '.py')
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(original, target)
        if digest(target) != expected or digest(original) != expected:
            raise ValueError('A legacy file changed during backup. No cleanup was performed for that file.')
        original.unlink()


def restore_native_modes(root):
    if os.name == 'nt':
        return
    for name in ('START.sh', 'START.command', 'scripts/launch.sh', 'scripts/setup_desktop.sh', 'util/wolfdawn/bin/linux/wolf'):
        file = root / name
        if file.is_file() and not file.is_symlink():
            file.chmod(file.stat().st_mode | 0o111)


def prepare(root=ROOT, *, cache=None, profile=None, offline=False):
    root = Path(root).resolve()
    cache = regular_folder(cache or setup_home())
    profile = regular_folder(profile or profile_home())
    config = json.loads((root / 'desktop/setup-runtimes.json').read_text())
    if config.get('version') != 1:
        raise ValueError('Unsupported desktop setup manifest.')
    key = platform_key()
    if (profile / 'source-updates/transactions').is_dir():
        from desktop.source_updates import SourceInstallation
        SourceInstallation(root, profile).recover()
    verify_renderer(root)
    with setup_lock(cache):
        uv = ensure_uv(config, cache, key, offline)
        python = ensure_python(root, config, cache, uv, key, offline=offline)
        electron = ensure_electron(config, cache, key, offline=offline)
        workspace = regular_folder(resolve_workspace(root, profile))
        env = clean_environment(cache)
        migration = root / 'desktop/backend/migration.py'
        command = [python, '-I', '-B', migration, '--source', root, '--workspace', workspace]
        print('Preparing existing settings and saved work…', flush=True)
        captured = json.loads(run([*command, '--capture'], env=env, capture=True))
        restore_engines(root, Path(captured['backup']))
        run(command, env=env)
        retire_legacy_files(root, Path(captured['backup']))
        restore_native_modes(root)
        result = {'root': str(root), 'python': str(python), 'electron': str(electron),
                  'profile': str(profile), 'workspace': str(workspace), 'cache': str(cache)}
        atomic_json(profile / 'installation.json', result)
        return result


def launch(installation, *, offline=False, live=False, wait=False):
    env = clean_environment(Path(installation['cache']))
    env.update(DAZEDTL_PYTHON=installation['python'], DAZEDTL_DESKTOP_PROFILE=installation['profile'],
               DAZEDTL_DESKTOP_WORKSPACE=installation['workspace'], DAZEDTL_SOURCE_INSTALL=installation['root'],
               DAZEDTL_DESKTOP_PROVIDERS='0' if offline else os.getenv('DAZEDTL_DESKTOP_PROVIDERS', '1'),
               DAZEDTL_DESKTOP_ALLOW_LIVE='1' if live else '0')
    env.pop('ELECTRON_RUN_AS_NODE', None)
    command = [installation['electron'], str(Path(installation['root']) / 'desktop')]
    if wait:
        return subprocess.call(command, env=env, cwd=installation['root'])
    ready = Path(installation['profile']) / ('startup-' + uuid.uuid4().hex + '.json')
    env['DAZEDTL_STARTUP_RECEIPT'] = str(ready)
    log = Path(installation['profile']) / 'startup.log'
    with log.open('ab') as output:
        process = subprocess.Popen(command, env=env, cwd=installation['root'], stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=os.name != 'nt',
                                   creationflags=(getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) | getattr(subprocess, 'DETACHED_PROCESS', 0)))
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if ready.exists():
                return 0
            code = process.poll()
            if code is not None:
                if code == 0:  # An existing instance received focus.
                    return 0
                raise RuntimeError(f'The app could not start. See {log}.')
            time.sleep(0.1)
        raise TimeoutError(f'The app has not finished starting. See {log}.')
    finally:
        ready.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup-only', action='store_true')
    parser.add_argument('--offline', action='store_true', help='Use cached downloads and disable provider requests')
    parser.add_argument('--live', action='store_true', help='Enable the separately capped development API broker')
    parser.add_argument('--providers', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--wait', action='store_true', help='Keep this terminal attached to the application')
    args = parser.parse_args(argv)
    try:
        print('Preparing DazedTL. First setup downloads its runtimes; later starts reuse them.', flush=True)
        installation = prepare(offline=args.offline)
        print('DazedTL is ready.', flush=True)
        return 0 if args.setup_only else launch(installation, offline=args.offline, live=args.live, wait=args.wait)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Setup stopped: {error}\nYour existing files were retained. Correct the problem and launch DazedTL again.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
