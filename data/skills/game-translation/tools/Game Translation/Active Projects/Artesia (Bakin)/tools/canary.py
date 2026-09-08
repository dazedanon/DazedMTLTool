"""Build, install and prove a canary patch before anything is translated.

    canary.py build      inject a handful of obviously-English strings
    canary.py install    copy dist_canary into the game and patch the config
    canary.py uninstall  put the game back exactly as it was

The point is to prove the DELIVERY path end to end - scramble, overlay hook,
temp folder, engine - while the text is still 100% Japanese, so a failure here
is unambiguous. Doing it after a real run means a blank screen could be the
hook, the scramble, the injector or the translation, and telling those apart
costs hours.

What it changes: the window title, the game title and subtitle, three glossary
buttons and one map name. Nothing else, and `uninstall` restores the config
byte-for-byte from the backup it takes.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from artl import config, store                                   # noqa: E402

CANARY = [
    # The window title comes from the GameSettings ROM ITEM's own `name`, not
    # from `meta.title`. Both hold the same Japanese string, so translating one
    # and shipping the other looks like the whole patch failed. Found by this
    # canary; keep both here.
    ("R:d24df012-3177-49f2-8bf3-12481548dcba:name", "CANARY WINDOW"),
    ("T:title", "CANARY TITLE"),
    ("T:subTitle", "CANARY SUBTITLE"),
    ("G:yes", "CANARY YES"),
    ("G:no", "CANARY NO"),
    ("G:save", "CANARY SAVE"),
    ("G:status", "CANARY STATUS"),
]


def build(cfg):
    import json
    docs = store.load_docs(cfg["store_dir"])
    have = {u["key"] for _p, doc in docs for u in doc["units"]}
    pairs = [(k, v) for k, v in CANARY if k in have]
    missing = [k for k, _v in CANARY if k not in have]
    if missing:
        print("not present in this game, skipped: %s" % ", ".join(missing))

    # One map name too, because a translated map name RENAMES the rom file and
    # that is the one part of delivery the hook has to handle specially.
    for _p, doc in docs:
        for u in doc["units"]:
            if u["kind"] == "mapname":
                pairs.append((u["key"], "Canary Map"))
                break
        if len(pairs) > len(CANARY):
            break

    path = os.path.join(cfg["work_dir"], "canary.jsonl")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for k, v in pairs:
            f.write(json.dumps({"key": k, "en": v}, ensure_ascii=False) + "\n")
    print("%d canary strings -> %s" % (len(pairs), path))

    out = os.path.join(ROOT, "out_canary")
    env = dict(os.environ, BAKIN_DATA=os.path.join(cfg["game_dir"], "data"))
    rc = subprocess.call([cfg["bakintl"], "inject", cfg["proj_dir"], path, out],
                         env=env)
    if rc:
        return rc
    return subprocess.call(
        [sys.executable, os.path.join(HERE, "build_patch.py"),
         cfg["proj_dir"], out, os.path.join(ROOT, "dist_canary"),
         os.path.join(ROOT, "BakinTLHook", "BakinTranslationHook.dll")])


def install(cfg, dist=None):
    dist = dist or os.environ.get("ARTL_DIST") or os.path.join(ROOT, "dist_canary")
    data = os.path.join(cfg["game_dir"], "data")
    cfgfile = os.path.join(data, "bakinplayer.exe.config")
    backup = cfgfile + ".pre-translation"
    if not os.path.exists(backup):
        shutil.copy2(cfgfile, backup)
        print("backed up %s" % backup)
    src = os.path.join(dist, "data")
    n = 0
    for dirpath, _d, files in os.walk(src):
        for fn in files:
            s = os.path.join(dirpath, fn)
            d = os.path.join(data, os.path.relpath(s, src))
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
            n += 1
    print("copied %d file(s) into %s" % (n, data))
    sys.path.insert(0, HERE)
    from build_patch import patch_config
    print("config: %s" % ("patched" if patch_config(cfgfile) else "already patched"))
    return 0


def uninstall(cfg):
    data = os.path.join(cfg["game_dir"], "data")
    cfgfile = os.path.join(data, "bakinplayer.exe.config")
    backup = cfgfile + ".pre-translation"
    if os.path.exists(backup):
        shutil.copy2(backup, cfgfile)
        print("restored %s" % cfgfile)
    tl = os.path.join(data, "translation")
    if os.path.isdir(tl):
        shutil.rmtree(tl)
        print("removed %s" % tl)
    dll = os.path.join(data, "BakinTranslationHook.dll")
    if os.path.exists(dll):
        os.unlink(dll)
        print("removed %s" % dll)
    return 0


if __name__ == "__main__":
    # Every path here contains Japanese; the default console codepage cannot
    # print them and the traceback would look like a copy failure.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = config.load()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    sys.exit({"build": build, "install": install, "uninstall": uninstall}[cmd](cfg))
