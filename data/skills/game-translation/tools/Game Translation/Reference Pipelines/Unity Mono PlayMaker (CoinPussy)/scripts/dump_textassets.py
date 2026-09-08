#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dump_textassets.py — dump every TextAsset out of the shipped Unity data files.

The AssetRipper export of this game contains no TextAsset folder, yet the game's
entire scripted dialogue lives in TextAsset CSVs inside `resources.assets`
(headers like `EventID,MessageJP,Announce,Animation,Facial,...`). A binary sweep
of the shipped data files found them; this dumps them properly with UnityPy so
the extractor can parse real files instead of carving bytes.

    python tools/scripts/dump_textassets.py [--data <CoinPussy_Data>] [--out <dir>]
"""

import argparse
import os
import re
import sys

DATA_FILES_RE = re.compile(
    r"^(globalgamemanagers(\.assets)?|level\d+|sharedassets\d+\.assets|resources\.assets)$")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    game = os.path.dirname(os.path.dirname(here))
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(game, "CoinPussy_Data"))
    ap.add_argument("--out", default=os.path.join(game, "tools", "extracted", "textassets"))
    args = ap.parse_args()

    try:
        import UnityPy
    except ImportError:
        sys.exit("ERROR: pip install UnityPy")

    os.makedirs(args.out, exist_ok=True)
    names = sorted(f for f in os.listdir(args.data) if DATA_FILES_RE.match(f))
    if not names:
        sys.exit(f"No Unity data files under {args.data}")

    total = 0
    seen = {}
    for name in names:
        path = os.path.join(args.data, name)
        env = UnityPy.load(path)
        n = 0
        for obj in env.objects:
            if obj.type.name != "TextAsset":
                continue
            data = obj.read()
            asset_name = getattr(data, "m_Name", None) or getattr(data, "name", None) or f"{obj.path_id}"
            script = getattr(data, "m_Script", None)
            if script is None:
                script = getattr(data, "script", b"")
            if isinstance(script, str):
                blob = script.encode("utf-8", "surrogateescape")
            else:
                blob = bytes(script or b"")
            safe = re.sub(r'[<>:"/\\|?*]', "_", str(asset_name)).strip() or str(obj.path_id)
            # Names repeat across files; keep every one distinct.
            key = safe.lower()
            seen[key] = seen.get(key, 0) + 1
            suffix = "" if seen[key] == 1 else f"__{seen[key]}"
            ext = ".csv" if b"," in blob[:200] and b"\n" in blob[:4000] else ".txt"
            out = os.path.join(args.out, f"{safe}{suffix}{ext}")
            with open(out, "wb") as f:
                f.write(blob)
            n += 1
            total += 1
        print(f"{name:28s} {n:5d} TextAsset(s)")
    print(f"\n{total} TextAssets -> {args.out}")


if __name__ == "__main__":
    main()
