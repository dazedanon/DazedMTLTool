#!/usr/bin/env python3
"""Native bundled-tool acceptance using generated data; no game/provider inputs.

Run natively on each OS. Linux --wine adds Windows compatibility checks in a
new disposable prefix; it never claims to be native Windows validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def ace_data():
    # Minimal Marshal 4.8 containers, following the Ruby format specification:
    # https://docs.ruby-lang.org/en/master/language/marshal_rdoc.html
    def number(value):
        if value == 0:
            return b'\0'
        if value < 123:
            return bytes([value + 5])
        raw = value.to_bytes((value.bit_length() + 7) // 8, 'little')
        return bytes([len(raw)]) + raw

    def symbol(value):
        raw = value.encode()
        return b':' + number(len(raw)) + raw

    def string(value):
        raw = value.encode('utf-8')
        return b'I"' + number(len(raw)) + raw + number(1) + symbol('E') + b'T'

    fields = {'@id': b'i' + number(1), '@name': string('薬'),
              '@description': string('体力を回復する。'), '@note': string('Keep this note'),
              '@price': b'i' + number(50)}
    item = (b'\x04\x08[' + number(2) + b'0o' + symbol('RPG::Item') + number(len(fields))
            + b''.join(symbol(key) + value for key, value in fields.items()))
    values = {name + '.rvdata2': b'\x04\x08[\0' for name in (
        'CommonEvents', 'System', 'Actors', 'Animations', 'Armors', 'Classes',
        'Enemies', 'Skills', 'States', 'Tilesets', 'Troops', 'Weapons', 'Scripts')}
    return {**values, 'MapInfos.rvdata2': b'\x04\x08{\0', 'Items.rvdata2': item}


def rgss3_archive(files):
    # Fixture encoder for the bundled decrypter's public RGSS3A contract:
    # https://github.com/uuksu/RPGMakerDecrypter/blob/master/RPGMakerDecrypter.RGSSAD/RGSSADv3.cs
    u32 = lambda value: struct.pack('<I', value & 0xffffffff)
    seed = 0x1254
    key = seed * 9 + 3
    entries = [(name.encode('utf-8'), raw) for name, raw in files.items()]
    offset = 12 + sum(16 + len(name) for name, _ in entries) + 16
    table, payload = bytearray(), bytearray()
    for index, (name, raw) in enumerate(entries):
        file_key = 0xdeadb33f + index
        table.extend(b''.join(u32(value ^ key) for value in (offset, len(raw), file_key, len(name))))
        table.extend(byte ^ u32(key)[pos % 4] for pos, byte in enumerate(name))
        for pos in range(0, len(raw), 4):
            payload.extend(byte ^ u32(file_key)[part] for part, byte in enumerate(raw[pos:pos + 4]))
            file_key = (file_key * 7 + 3) & 0xffffffff
        offset += len(raw)
    return b'RGSSAD\0\3' + u32(seed) + table + u32(key) * 4 + payload


def inventory(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


def check(backend, use_wine, root, report):
    deadline = time.monotonic() + 180
    temporary = root / 'native-temp'
    temporary.mkdir()
    env = {key: value for key, value in os.environ.items() if key in {
        'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'HOME', 'USERPROFILE', 'APPDATA',
        'LOCALAPPDATA', 'LANG', 'LC_ALL', 'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY',
        'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH',
    }}
    env.update(PYTHON_DOTENV_DISABLED='1', TMPDIR=str(temporary),
               DOTNET_BUNDLE_EXTRACT_BASE_DIR=str(temporary / 'dotnet'))
    if os.name == 'nt':
        env.update(TEMP=str(temporary), TMP=str(temporary))
    if use_wine:
        if sys.platform != 'linux' or not shutil.which('wine') or not shutil.which('wineserver'):
            raise ValueError('--wine requires Wine on Linux.')
        env.update(WINEPREFIX=str(root / 'wine'), WINEDEBUG='-all',
                   WINEDLLOVERRIDES='winemenubuilder.exe=d;mscoree,mshtml=')

    def run(label, argv, cwd, *, wine=False):
        if time.monotonic() >= deadline:
            raise TimeoutError('Native tool acceptance exceeded its 180-second deadline.')
        logfile = root / f'{len(report["steps"]):02d}.log'
        executable = Path(argv[0])
        if executable.is_absolute() and executable.is_relative_to(backend):
            name = executable.relative_to(backend).as_posix()
            if name not in report['tools']:
                with executable.open('rb') as handle:
                    report['tools'][name] = hashlib.file_digest(handle, 'sha256').hexdigest()
        def argument(value):
            if wine and isinstance(value, Path) and value.is_absolute() and value != executable:
                return 'Z:' + str(value).replace('/', '\\')
            return str(value)
        command = (['wine'] if wine else []) + [argument(value) for value in argv]
        started = time.monotonic()
        # File-backed output also bounds shutdown when a native bootstrap
        # service inherits the child's handles (notably first-run Wine).
        with logfile.open('wb') as output:
            process = subprocess.run(command, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT,
                                     timeout=min(45, max(1, deadline - time.monotonic())))
        detail = {'label': label, 'seconds': round(time.monotonic() - started, 3),
                  'returncode': process.returncode, 'log': logfile.read_text(encoding='utf-8', errors='replace')[-6000:]}
        report['steps'].append(detail)
        if process.returncode:
            raise RuntimeError(f'{label} exited {process.returncode}: {detail["log"][-1000:]}')

    try:
        if os.name == 'nt':
            # Exercise the actual Windows reparse-point boundary, which a
            # POSIX symlink fixture cannot establish for native Windows.
            game, outside = root / 'Junction game', root / 'Other game'
            game.mkdir()
            outside.mkdir()
            junction = game / 'Data'
            run('Windows directory-junction guard', ['cmd', '/c', 'mklink', '/J', junction, outside], root)
            try:
                sys.path.insert(0, str(backend))
                from util.project_preparation import _game_path
                assert _game_path(game, game / 'allowed.json') == game / 'allowed.json'
                try:
                    _game_path(game, junction / 'new-file.json')
                except ValueError:
                    report['junction_guard'] = 'passed-native-windows'
                else:
                    raise AssertionError('A Windows directory junction bypassed the game write boundary.')
                assert not any(outside.iterdir())
            finally:
                junction.rmdir()
        if use_wine:
            run('Initialize private Wine prefix', ['cmd', '/c', 'exit', '0'], root, wine=True)
        platforms = [('windows' if os.name == 'nt' else 'macos' if sys.platform == 'darwin' else 'linux', False)]
        if use_wine:
            platforms.append(('windows', True))
        for platform, wine in platforms:
            binary = backend / 'util/wolfdawn/bin' / platform / ('wolf.exe' if platform == 'windows' else 'wolf')
            if not binary.is_file():
                raise FileNotFoundError(f'No bundled WolfDawn binary for {platform}: {binary}')
            game = root / ('WOLF 日本語 ' + platform)
            source = game / 'Data'
            (source / 'Evtext').mkdir(parents=True)
            (source / 'Evtext/001.txt').write_bytes('おはようございます。\n'.encode('cp932'))
            (source / 'preserved.bin').write_bytes(bytes(range(256)))
            original = inventory(source)
            run(f'{platform} WOLF pack', [binary, 'pack', source, '-o', game / 'Data.wolf'], game, wine=wine)
            archive = (game / 'Data.wolf').read_bytes()
            run(f'{platform} WOLF unpack', [binary, 'unpack', game / 'Data.wolf', '-o', game / 'unpacked'], game, wine=wine)
            assert inventory(game / 'unpacked') == original, 'WOLF archive changed its payload.'
            assert inventory(source) == original, 'WOLF pack changed its input.'
            (source / 'Evtext/001.txt').write_text('Good morning.\n', encoding='utf-8')
            run(f'{platform} WOLF repack with original format', [binary, 'pack', source, '-o', game / 'translated.wolf', '--like', game / 'Data.wolf'], game, wine=wine)
            run(f'{platform} WOLF verify repack', [binary, 'unpack', game / 'translated.wolf', '-o', game / 'verified'], game, wine=wine)
            assert inventory(game / 'verified') == inventory(source), 'WOLF repack lost translated or untouched data.'
            assert (game / 'Data.wolf').read_bytes() == archive, 'Original WOLF archive changed.'
        if os.name == 'nt' or use_wine:
            game = root / 'Ace 日本語 game'
            game.mkdir()
            files = ace_data()
            archive = rgss3_archive({'Data\\' + name: raw for name, raw in files.items()})
            (game / 'Game.rgss3a').write_bytes(archive)
            tools = backend / 'util/ace/offline'
            run('Ace decrypt', [tools / 'RPGMakerDecrypter-cli.exe', game / 'Game.rgss3a'], game, wine=use_wine)
            assert inventory(game / 'Data') == {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}
            run('Ace extract JSON', [tools / 'RV2JSON.exe', '-c'], game, wine=use_wine)
            path = game / 'ace_json/Items.json'
            value = json.loads(path.read_text(encoding='utf-8'))
            assert value[1]['name'] == '薬' and value[1]['price'] == 50
            value[1]['name'] = 'Medicine'
            path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            run('Ace pack translation', [tools / 'RV2JSON.exe', '-u'], game, wine=use_wine)
            assert (game / 'Data/backups/Items.rvdata2').read_bytes() == files['Items.rvdata2']
            run('Ace read back translation', [tools / 'RV2JSON.exe', '-c', '-j', 'verified_json'], game, wine=use_wine)
            changed = json.loads((game / 'verified_json/Items.json').read_text(encoding='utf-8'))[1]
            assert changed['name'] == 'Medicine' and changed['note'] == 'Keep this note' and changed['price'] == 50
            assert (game / 'Game.rgss3a').read_bytes() == archive
            report['ace'] = 'wine-compatibility' if use_wine else 'native-windows'
        else:
            report['ace'] = 'Windows tool; requires a Windows run or an explicit Wine compatibility check.'
    finally:
        if use_wine:
            subprocess.run(['wineserver', '-k'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packaged', action='store_true', help='Use the binaries inside the locally built package')
    parser.add_argument('--wine', action='store_true', help='Also exercise Windows binaries with a disposable Wine prefix on Linux')
    parser.add_argument('--output', type=Path, default=ROOT / '.tmp-ui/desktop-evidence/native-tools.json')
    args = parser.parse_args()
    backend = ROOT
    if args.packaged:
        result = json.loads((ROOT / 'desktop/out/package-result.json').read_text())
        backend = Path(result['packages'][0]) / ('DazedTL.app/Contents/Resources/backend' if sys.platform == 'darwin' else 'resources/backend')
    report = {'platform': sys.platform, 'backend': str(backend), 'wine_compatibility': args.wine, 'steps': [], 'tools': {}}
    if args.packaged:
        report['package_id'] = result['packageId']
    try:
        with tempfile.TemporaryDirectory(prefix='dazedtl-native-tools-') as temporary:
            check(backend, args.wine, Path(temporary), report)
        report['status'] = 'passed'
    except Exception as exc:
        report.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'report': str(args.output), 'error': report.get('error')}))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
