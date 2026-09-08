"""Patch the YU-RIS yscfg.ybn window title used by CreateWindowExA."""
import argparse
from pathlib import Path

TITLE_LEN_OFF = 0x4C
TITLE_OFF = 0x4E


def patch_title(path, title):
    p = Path(path)
    data = bytearray(p.read_bytes())
    if data[:4] != b'YSCF':
        raise RuntimeError(f'{p} is not a YSCF config file')

    old_len = int.from_bytes(data[TITLE_LEN_OFF:TITLE_LEN_OFF + 2], 'little')
    old_raw = bytes(data[TITLE_OFF:TITLE_OFF + old_len])
    new_raw = title.encode('cp932')
    if len(new_raw) > old_len:
        raise RuntimeError(f'new title is {len(new_raw)} bytes; max is {old_len}')

    data[TITLE_LEN_OFF:TITLE_LEN_OFF + 2] = len(new_raw).to_bytes(2, 'little')
    data[TITLE_OFF:TITLE_OFF + old_len] = new_raw + b'\x00' * (old_len - len(new_raw))
    p.write_bytes(data)

    old_title = old_raw.decode('cp932', errors='replace').encode('unicode_escape').decode('ascii')
    print(f'{p}: {old_title} -> {title}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--title', default='Elfhime')
    args = ap.parse_args()
    for file in args.files:
        patch_title(file, args.title)


if __name__ == '__main__':
    main()
