"""Walk the rbpack resource index structurally.

    index_walk.py <data.rbpack> <out.txt> [scanMB] [prefix]

The reference pipeline harvested paths with a regex anchored on a fixed set of
project roots (`res\\`, `map\\`, ...). This game's index uses different roots
entirely (`character\\3D\\effekseer\\...`), so the anchor is re-measured here by
walking the table instead of pattern-matching it.

The index is a contiguous run of `[path][17-byte record]` entries starting at
`res_offset + 5`. The stride is exact: the next path begins 17 bytes after the
last byte of the current one, which is what makes the walk self-checking - a
wrong extension guess desynchronises immediately and the walk stops.

This build stores the paths relative to the project's `res` folder, while the
reference game stored them with the `res` component already in the string, so
the prefix is a per-game measurement: probe one entry both ways with
`BakinRes probe` and pass whichever the engine serves.

Every path is still only a candidate; `BakinRes` confirms each one against the
engine's own `FSEx.existsResourceFile`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rbpack import RbPack
from scan_resources import descramble_fast

RECORD = 17
FIRST = 5

EXTS = (b'.png', b'.bmp', b'.fbx', b'.ogg', b'.efkefc', b'.efkmat',
        b'.efkmodel', b'.efk', b'.wav', b'.mp3', b'.m4a', b'.webm', b'.hdr',
        b'.ttf', b'.otf', b'.tga', b'.dds', b'.jpeg', b'.jpg', b'.cgh', b'.cg',
        b'.txt', b'.json', b'.csv', b'.mp4', b'.vrm', b'.dae', b'.gltf',
        b'.glb', b'.mtl', b'.obj')

SAFE = set(b'0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
           b'_-.' + b'/' + b'\\' + b'()[]{}+&!#$%,;=@^~ \'') | set(range(0x80, 0x100))


def walk(plain, start=FIRST):
    """Yield paths until the stride desynchronises."""
    p = start
    n = len(plain)
    while p < n:
        q = p
        while q < n and plain[q] in SAFE:
            q += 1
        run = plain[p:q]
        if len(run) < 4:
            break
        # Earliest match wins, but `.efk` is a prefix of `.efkmat`, so among
        # extensions starting at the same offset the longest one is the real end.
        at, cut = None, None
        for e in EXTS:
            i = run.find(e)
            if i == -1:
                continue
            if at is None or i < at or (i == at and i + len(e) > cut):
                at, cut = i, i + len(e)
        if cut is None:
            break
        yield p, run[:cut]
        p += cut + RECORD


def main(pack_path, out_path, scan_mb=32, prefix='res' + os.sep):
    pk = RbPack(pack_path)
    total = os.path.getsize(pack_path) - pk.res_offset
    limit = min(total, int(scan_mb) * 1024 * 1024)
    with open(pack_path, 'rb') as f:
        f.seek(pk.res_offset)
        raw = f.read(limit)
    plain = descramble_fast(raw, pk.res_offset)

    paths, last = [], FIRST
    for off, b in walk(plain):
        paths.append(b.decode('utf-8', 'replace'))
        last = off + len(b) + RECORD
    with open(out_path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(prefix + p for p in paths))
    print('region %d bytes, scanned %d' % (total, limit))
    print('entries %d, index ends at +%d' % (len(paths), last))
    print('-> %s' % out_path)
    return 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:5]))
