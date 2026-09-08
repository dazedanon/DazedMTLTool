"""Flatten an extracted asset tree into one folder for eyeballing.

    flatten_images.py <srcDir> <dstDir> [ext ...]

Names each copy after its relative path so the original location is still
readable at a glance. Windows caps a path at 260 characters unless long paths
are enabled, so an over-long name is trimmed in the middle and given a short
hash to keep it unique; `_map.tsv` in the destination maps every flat name back
to its real path.
"""

import hashlib
import os
import shutil
import sys

MAX_NAME = 170


def flatten(rel):
    name = rel.replace('\\', '_').replace('/', '_')
    if len(name) <= MAX_NAME:
        return name
    stem, ext = os.path.splitext(name)
    tag = hashlib.sha1(rel.encode('utf-8')).hexdigest()[:8]
    keep = MAX_NAME - len(ext) - len(tag) - 5
    return '%s~~%s~%s%s' % (stem[:keep // 2], stem[-(keep - keep // 2):], tag, ext)


def main(src, dst, *exts):
    exts = tuple(e.lower() if e.startswith('.') else '.' + e.lower()
                 for e in (exts or ('.png',)))
    os.makedirs(dst, exist_ok=True)

    files = []
    for dirpath, _, names in os.walk(src):
        for fn in names:
            if fn.lower().endswith(exts):
                p = os.path.join(dirpath, fn)
                files.append((os.path.relpath(p, src), p))
    files.sort()

    used = {}
    rows = []
    total = 0
    for rel, full in files:
        name = flatten(rel)
        if name in used:
            stem, ext = os.path.splitext(name)
            name = '%s~%d%s' % (stem, len(used), ext)
        used[name] = rel
        shutil.copy2(full, os.path.join(dst, name))
        total += os.path.getsize(full)
        rows.append((name, rel))

    with open(os.path.join(dst, '_map.tsv'), 'w', encoding='utf-8') as w:
        w.write('flatname\toriginalpath\n')
        for name, rel in rows:
            w.write('%s\t%s\n' % (name, rel))

    print('copied %d files (%.2f GB) -> %s' % (len(rows), total / 1e9, dst))
    longest = max((len(n) for n, _ in rows), default=0)
    print('longest flat name: %d chars' % longest)
    return 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
