"""Flatten an extracted asset tree into one folder of viewable PNGs.

    flatten_png.py <srcDir> <dstDir>

Like `flatten_images.py`, but every output is a real PNG: BMPs are converted so
the whole set opens in one viewer, and the seven files this game ships with a
`.png` name over BMP bytes are handled by their magic rather than their
extension. A converted file keeps its original extension in the flat name
(`..._foo.bmp.png`) so nothing is silently confused with a shipped PNG.

`_map.tsv` in the destination maps every flat name back to its real path.
"""

import hashlib
import os
import shutil
import sys

from PIL import Image

MAX_NAME = 170
SRC_EXT = ('.png', '.bmp')


def flatten(rel):
    name = rel.replace('\\', '_').replace('/', '_')
    if len(name) <= MAX_NAME:
        return name
    stem, ext = os.path.splitext(name)
    tag = hashlib.sha1(rel.encode('utf-8')).hexdigest()[:8]
    keep = MAX_NAME - len(ext) - len(tag) - 5
    return '%s~~%s~%s%s' % (stem[:keep // 2], stem[-(keep - keep // 2):], tag, ext)


def is_png(path):
    with open(path, 'rb') as f:
        return f.read(8) == b'\x89PNG\r\n\x1a\n'


def main(src, dst):
    # Asset paths are Japanese; the default console codepage cannot print them.
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    os.makedirs(dst, exist_ok=True)
    files = []
    for dirpath, _, names in os.walk(src):
        for fn in names:
            if fn.lower().endswith(SRC_EXT):
                p = os.path.join(dirpath, fn)
                files.append((os.path.relpath(p, src), p))
    files.sort()

    used, rows = {}, []
    copied = converted = failed = 0
    total = 0
    for rel, full in files:
        name = flatten(rel)
        direct = is_png(full)
        if not direct:
            name += '.png'
        if name in used:
            stem, ext = os.path.splitext(name)
            name = '%s~%d%s' % (stem, len(used), ext)
        out = os.path.join(dst, name)
        try:
            if direct:
                shutil.copy2(full, out)
                copied += 1
            else:
                with Image.open(full) as im:
                    im.save(out, 'PNG')
                converted += 1
        except Exception as exc:
            failed += 1
            print('FAILED %s: %s' % (rel, exc))
            continue
        used[name] = rel
        total += os.path.getsize(out)
        rows.append((name, rel))

    with open(os.path.join(dst, '_map.tsv'), 'w', encoding='utf-8') as w:
        w.write('flatname\toriginalpath\n')
        for name, rel in rows:
            w.write('%s\t%s\n' % (name, rel))

    print('copied %d, converted %d, failed %d -> %s (%.2f GB)'
          % (copied, converted, failed, dst, total / 1e9))
    print('longest flat name: %d chars' % max((len(n) for n, _ in rows), default=0))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:3]))
