"""Harvest asset paths out of the rbpack resource region.

    scan_resources.py <data.rbpack> <out.txt> [scanMB]

The region is scrambled by absolute file offset like everything else, and opens
with an index of NUL-free path strings. Rather than reverse the native index
layout, pull every path-shaped run out of the descrambled bytes; each candidate
can then be confirmed against the engine's own FSEx.existsResourceFile.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rbpack import RbPack
from scramble import _DELTA_DATA

CHUNK = 1 << 22
EXT = (rb'png|jpg|jpeg|bmp|tga|dds|hdr|webm|ogg|wav|mp3|m4a|fbx|vrm'
       rb'|cg|cgh|txt|json|csv|ttf|otf|def|dae|gltf|glb')
# Anchored on the project-relative roots the engine uses, so index binary either
# side of a path string cannot bleed into the match.
PATH = re.compile(rb'(?:res|lib|map|script|battlescript|terrainmap)[\\/]'
                  rb'[0-9A-Za-z_\-./\\()\[\]{}+&!#$%,;=@^~ \x80-\xff]{1,250}?\.(?:' + EXT + rb')',
                  re.IGNORECASE)
# No trailing boundary assertion: index binary follows each path, so the byte
# after ".png" is arbitrary and a lookahead just makes the match run on into the
# next entry. Non-greedy matching stops at the first extension instead.


def descramble_fast(buf, start):
    """Same transform as scramble.descramble, done 16 strides at a time."""
    out = bytearray(buf)
    for phase in range(16):
        d = _DELTA_DATA[phase]
        if not d:
            continue
        first = (phase - start) % 16
        sl = out[first::16]
        out[first::16] = bytes((b - d) & 0xFF for b in sl)
    return bytes(out)


def main(pack_path, out_path, scan_mb=64):
    pk = RbPack(pack_path)
    total = os.path.getsize(pack_path) - pk.res_offset
    limit = min(total, int(scan_mb) * 1024 * 1024)
    print('resource region %d bytes, scanning first %d' % (total, limit))

    found, order = set(), []
    with open(pack_path, 'rb') as f:
        f.seek(pk.res_offset)
        done = 0
        carry = b''
        carry_off = pk.res_offset
        while done < limit:
            off = pk.res_offset + done
            raw = f.read(min(CHUNK, limit - done))
            if not raw:
                break
            plain = descramble_fast(raw, off)
            buf = carry + plain
            base = carry_off
            for m in PATH.finditer(buf):
                # a match touching the tail may be truncated; leave it for the carry
                if m.end() > len(buf) - 300 and done + len(raw) < limit:
                    continue
                p = m.group().decode('utf-8', 'replace')
                if p not in found:
                    found.add(p)
                    order.append(p)
            carry = buf[-300:]
            carry_off = base + len(buf) - 300
            done += len(raw)
            if done % (CHUNK * 16) == 0:
                print('  %d MB -> %d paths' % (done >> 20, len(found)))

    with open(out_path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(order))
    print('paths: %d -> %s' % (len(order), out_path))
    return 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:4]))
