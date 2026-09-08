"""Turn an injected (plain, English) Bakin project into a distributable patch.

    build_patch.py <originalProj> <injectedProj> <distDir> <hookDll>

The engine descrambles every file it reads off disk that is not served from the
resource pack, so the shipped roms have to go back out SCRAMBLED. Only files
that actually changed are shipped, except the map folder: translated map names
change the map file names, so the hook replaces that folder wholesale and the
whole set has to be present.
"""

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scramble import scramble

CONFIG_HOOK = """    <appDomainManagerAssembly value="BakinTranslationHook, Version=0.0.0.0, Culture=neutral, PublicKeyToken=null" />
    <appDomainManagerType value="BakinTranslationHook" />
"""


def rel_rbr(root):
    out = {}
    for dirpath, _, files in os.walk(root):
        for fn in files:
            if fn.lower().endswith('.rbr'):
                p = os.path.join(dirpath, fn)
                out[os.path.relpath(p, root).replace('\\', '/')] = p
    return out


def main(orig, inj, dist, hook_dll):
    a, b = rel_rbr(orig), rel_rbr(inj)
    tl = os.path.join(dist, 'data', 'translation')
    if os.path.exists(dist):
        shutil.rmtree(dist)
    os.makedirs(tl)

    maps_changed = any(k.startswith('map/') for k in set(a) ^ set(b)) or any(
        k.startswith('map/') and open(a[k], 'rb').read() != open(b[k], 'rb').read()
        for k in set(a) & set(b))

    shipped = 0
    total = 0
    for k, p in sorted(b.items()):
        data = open(p, 'rb').read()
        is_map = k.startswith('map/')
        same = k in a and open(a[k], 'rb').read() == data
        if same and not (is_map and maps_changed):
            continue
        dst = os.path.join(tl, k.replace('/', os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, 'wb').write(scramble(data))
        shipped += 1
        total += len(data)

    shutil.copy(hook_dll, os.path.join(dist, 'data', os.path.basename(hook_dll)))
    print('shipped %d rom files (%.1f MB), maps replaced wholesale: %s'
          % (shipped, total / 1e6, maps_changed))
    return 0


def patch_config(path):
    """Insert the AppDomainManager hook into bakinplayer.exe.config, idempotently."""
    text = open(path, encoding='utf-8-sig').read()
    if 'appDomainManagerAssembly' in text:
        return False
    if '<runtime>' not in text:
        raise SystemExit('no <runtime> element in ' + path)
    text = text.replace('<runtime>', '<runtime>\n' + CONFIG_HOOK.rstrip('\n'), 1)
    open(path, 'w', encoding='utf-8-sig', newline='').write(text)
    return True


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'config':
        print('patched' if patch_config(sys.argv[2]) else 'already patched')
    else:
        sys.exit(main(*sys.argv[1:5]))
