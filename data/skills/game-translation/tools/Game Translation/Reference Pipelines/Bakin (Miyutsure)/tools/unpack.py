"""Unpack a Bakin data.rbpack into a plain, descrambled project folder.

    unpack.py <game>\\data\\data.rbpack <projDir>

The launcher descrambles executable payloads itself and leaves everything else
scrambled on disk for the engine to handle, so this mirrors that split: the
extensions the launcher handles keep the launcher's table, everything else gets
the engine's.
"""

import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rbpack import RbPack
from scramble import descramble

LAUNCHER_EXT = {'.dlp', '.dlp_d', '.dll', '.exe', '.cg', '.cgh'}


def main(pack_path, out_dir):
    pk = RbPack(pack_path)
    if pk.check_drm() is None:
        raise SystemExit('DRM hash does not match; refusing to unpack')
    print('version %d  label %r  zip %d  resources start at %d'
          % (pk.version, pk.label, pk.zip_len, pk.res_offset))

    z = zipfile.ZipFile(io.BytesIO(pk.read_zip()))
    n = 0
    for info in z.infolist():
        if info.is_dir():
            continue
        data = z.read(info)
        ext = os.path.splitext(info.filename)[1].lower()
        # The launcher already descrambles these on extraction.
        data = descramble(data, launcher=(ext in LAUNCHER_EXT))
        dst = os.path.join(out_dir, info.filename.replace('/', os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, 'wb') as f:
            f.write(data)
        n += 1

    bad = []
    for dirpath, _, files in os.walk(out_dir):
        for fn in files:
            if fn.lower().endswith('.rbr') and open(os.path.join(dirpath, fn), 'rb').read(5) != b'YUKAR':
                bad.append(fn)
    print('extracted %d files; rom files failing the YUKAR check: %d' % (n, len(bad)))
    if bad:
        print('  ', bad[:5])
        print('  the scramble table is wrong for this data version - re-derive it')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2]))
