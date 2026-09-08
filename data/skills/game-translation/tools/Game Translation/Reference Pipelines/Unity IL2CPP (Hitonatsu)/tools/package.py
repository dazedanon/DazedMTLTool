#!/usr/bin/env python3
"""Build the player-facing patch archive.

Ships the loader that is already installed in the game folder, minus everything
that is a dev artefact or a runtime cache. The layout mirrors goblin-toybox,
which is the proven BepInEx 6 IL2CPP shipping shape on this machine.

The archive is a patch, not a repack: it contains no game asset, only the
loader, the bundled .NET runtime and our plugin.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hitonatsu import common as C  # noqa: E402

# What a player needs, in the order they are listed in the README.
INCLUDE = [
    "winhttp.dll",              # Doorstop 4 proxy
    ".doorstop_version",
    "doorstop_config.ini",      # its [Il2Cpp] block points CoreCLR at dotnet/
    "dotnet",                   # bundled .NET 6 - why no runtime install is needed
    os.path.join("BepInEx", "core"),
    os.path.join("BepInEx", "config", "BepInEx.cfg"),
    os.path.join("BepInEx", "plugins", "HitonatsuTL"),
]

# Anything matching these never enters the archive, wherever it sits.
DENY = [
    "*.pdb",
    "*.log",
    "*.tmp",
    "untranslated.txt",         # harvest output - QA only
    "com.sw.hitonatsu.tl.cfg",  # shipping it freezes dev toggles onto the player
    "mistral_keys.txt",
    "*.env",
    "chainloader_typeloader.dat",
    "harmony_interop_cache.dat",
]

# Directories excluded wholesale even when nested under an INCLUDE entry.
DENY_DIRS = {"interop", "cache", "unity-libs", "dummy", "obj", "bin", "__pycache__"}


def denied(path: str) -> str | None:
    name = os.path.basename(path)
    for pat in DENY:
        if fnmatch.fnmatch(name, pat):
            return pat
    parts = path.replace("\\", "/").split("/")
    for p in parts[:-1]:
        if p in DENY_DIRS:
            return f"dir:{p}"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", default=C.GAME)
    ap.add_argument("--out", default=os.path.join(C.PROJECT, "dist",
                                                  "Hitonatsu-English-Patch.zip"))
    args = ap.parse_args()

    plugin_dir = os.path.join(args.game, "BepInEx", "plugins", "HitonatsuTL")
    if not os.path.exists(os.path.join(plugin_dir, "HitonatsuTL.dll")):
        raise SystemExit(f"plugin not built/deployed - run `dotnet build -c Release` "
                         f"in plugin/HitonatsuTL first ({plugin_dir})")

    # A harvest build is a QA build. Refuse rather than ship one.
    cfg = os.path.join(args.game, "BepInEx", "config", "com.sw.hitonatsu.tl.cfg")
    if os.path.exists(cfg):
        text = open(cfg, encoding="utf-8", errors="replace").read()
        for line in text.splitlines():
            if line.strip().lower().startswith("harvest") and "true" in line.lower():
                raise SystemExit("QA/Harvest is true in the game's config - the plugin "
                                 "would write untranslated.txt on a player's machine. "
                                 "Set it false, relaunch once, then package.")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    skipped: dict[str, int] = {}
    n = 0

    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for entry in INCLUDE:
            src = os.path.join(args.game, entry)
            if not os.path.exists(src):
                raise SystemExit(f"missing required item: {src}")
            if os.path.isfile(src):
                if denied(entry):
                    continue
                z.write(src, entry)
                n += 1
                continue
            for dp, dn, fn in os.walk(src):
                dn[:] = [d for d in dn if d not in DENY_DIRS]
                for f in fn:
                    full = os.path.join(dp, f)
                    rel = os.path.relpath(full, args.game)
                    why = denied(rel)
                    if why:
                        skipped[why] = skipped.get(why, 0) + 1
                        continue
                    z.write(full, rel)
                    n += 1

    size = os.path.getsize(args.out)
    print(f"{n} files, {size / 1_048_576:.1f} MB -> {args.out}")
    if skipped:
        print("excluded:")
        for why, count in sorted(skipped.items()):
            print(f"  {count:>4}  {why}")
    print("\nVerify by unzipping into a CLEAN copy of the game and running it: the "
          "config values are an intention, the absent log files are the evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
