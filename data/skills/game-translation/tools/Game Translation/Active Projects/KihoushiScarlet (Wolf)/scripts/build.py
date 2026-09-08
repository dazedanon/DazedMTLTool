#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py - everything after the translation: import -> inject -> font -> relayout
-> verify -> deploy, for 騎紅士スカーレット (Wolf RPG Editor).

    python scripts/build.py import      # mt-import + names-fill + names-check
    python scripts/build.py inject      # pristine -> build/DataEN (strings, then names)
    python scripts/build.py font        # repoint Game.dat's Font at a face GDI resolves
    python scripts/build.py relayout    # reflow EN to the measured box geometry
    python scripts/build.py deindent    # drop the JP alignment pad relayout needed
    python scripts/build.py verify      # roundtrip + semantic + residual-symbol sweep
    python scripts/build.py deploy      # mirror build/DataEN into the game folder
    python scripts/build.py all         # every step above, in order
    python scripts/build.py restore     # put the pristine Japanese data back

Two rules this script exists to enforce, both learned the hard way:

  * INJECT ORDER. Strings go in per file FIRST and the names pass runs LAST, in
    place over the already-injected files. Pointing the names pass back at the
    pristine originals rebuilds each file from Japanese and silently reverts
    everything the string pass wrote.

  * DEPLOY PACKAGES, IT DOES NOT BUILD. Editing the glossary, running every gate
    and then deploying ships the PREVIOUS inject with every gate green, because
    the gates read batch.json and the pristine tree and never the output. So the
    inject stamps what it was built from and deploy refuses a stale tree.
"""

import os
import re
import sys
import json
import glob
import time
import shutil
import hashlib
import argparse
import subprocess

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WOLF = os.environ.get(
    "WOLF_EXE", r"C:\Users\sw\Desktop\Projects\WolfDawn\target\release\wolf.exe")
GAME = os.environ.get(
    "SCARLET_GAME_DIR", r"c:\Users\sw\Desktop\Games\Crimson Knight Scarlet")

PRISTINE = os.path.join(WS, "pristine")
OUT = os.path.join(WS, "out")
BUILD = os.path.join(WS, "build")
DATAEN = os.path.join(BUILD, "DataEN")
STAMP = os.path.join(BUILD, "build-stamp.json")
BATCH = os.path.join(WS, "batch.json")

# The Font face shipped in Game.dat is "MSゴシック" (halfwidth), which GDI
# CreateFontW does not match - it silently falls back to Arial and every CJK
# glyph and every ★ ♡ ・ becomes tofu. The fullwidth form is the real face name
# and is present on every Windows install, so nothing has to be shipped.
FONT_FACE = "ＭＳ ゴシック"

DB_PROJECTS = ["DataBase", "CDataBase", "SysDatabase"]


def run(args, check=True, quiet=False):
    if not quiet:
        print("  $ " + " ".join(os.path.basename(a) if a == WOLF else a for a in args))
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    if out.strip() and not quiet:
        for line in out.rstrip().splitlines():
            print("    " + line)
    # exit 2 is "round-trip mismatch / inject guard skip / name-consistency failure".
    # It still writes every good line, so it is a warning, never a stop.
    if check and p.returncode not in (0, 2):
        sys.exit(f"FAILED (exit {p.returncode}): {' '.join(args)}")
    return p.returncode, out


def export_order():
    """The file list in the EXACT order `wolf mt-export` received it.

    An mt-batch id is `<file-index>|<json-pointer>`, and the index is a position in
    the list passed to mt-export - not a property of the file. Handing mt-import a
    different list (or the same list in a different order) shifts every index, and
    it does not fail loudly: it reports a pile of `unknown id` and `source-mismatch`
    and quietly writes the few that happen to line up. A first attempt here dropped
    names.json from the import and got `192 filled, 1251 source-mismatch,
    72846 unknown id` - 192 translations written into the WRONG rows.

    So the order is DERIVED from batch.json rather than re-declared, which makes it
    impossible for the two to disagree.
    """
    with open(BATCH, encoding="utf-8") as f:
        lines = json.load(f)["lines"]
    slots = {}
    for l in lines:
        slots.setdefault(int(l["id"].split("|", 1)[0]), l["file"])
    # A file with nothing pending never appears in the batch, so ~17 slots cannot be
    # observed. The order is therefore DECLARED here (it is the argument order the
    # export was run with) and then PROVEN against every slot that IS observable -
    # a declaration nobody checks is how this went wrong in the first place.
    on_disk = {os.path.basename(p): p for p in glob.glob(os.path.join(OUT, "*.json"))}
    head = ["names.json", "CommonEvent.json", "DataBase.json", "CDataBase.json",
            "SysDatabase.json", "GameDat.json"]
    maps = sorted(b for b in on_disk if b.startswith("map_"))
    declared = [b for b in head if b in on_disk] + maps
    extra = sorted(set(on_disk) - set(declared))
    if extra:
        raise SystemExit(f"export_order: {extra} is not covered by the declared order.")

    for idx, observed in sorted(slots.items()):
        base = os.path.basename(observed)
        if idx >= len(declared) or declared[idx] != base:
            raise SystemExit(
                f"export_order: batch.json says slot {idx} is {base!r} but the declared "
                f"order puts {declared[idx] if idx < len(declared) else '<none>'!r} there. "
                "The batch was exported from a different file list - importing would "
                "write translations into the wrong rows.")
    return [on_disk[b] for b in declared]


def extract_jsons():
    """Every out/*.json except names.json, in a stable order (for names-fill/check)."""
    files = sorted(glob.glob(os.path.join(OUT, "*.json")))
    return [f for f in files if os.path.basename(f) != "names.json"]


# --------------------------------------------------------------------------
# build stamp - cheap identity, so a consumer can refuse a stale producer
# --------------------------------------------------------------------------
def _tree_identity(root):
    """size+mtime of every file under root. Never a content hash - the pristine
    tree is small here, but the habit is what stops a 1.7 GB rehash elsewhere."""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            p = os.path.join(dirpath, fn)
            st = os.stat(p)
            h.update(os.path.relpath(p, root).encode("utf-8"))
            h.update(f"{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()[:16]


def current_inputs():
    st = os.stat(BATCH)
    return {
        "pristine": _tree_identity(PRISTINE),
        "batch_size": st.st_size,
        "batch_mtime": int(st.st_mtime),
        "font_face": FONT_FACE,
    }


def write_stamp(steps):
    os.makedirs(BUILD, exist_ok=True)
    data = current_inputs()
    data["steps"] = steps
    data["built_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(STAMP, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def read_stamp():
    if not os.path.exists(STAMP):
        return None
    with open(STAMP, encoding="utf-8") as f:
        return json.load(f)


def require_fresh(step_name, needs):
    """Refuse to run a consumer step over a producer output that is out of date."""
    stamp = read_stamp()
    if stamp is None:
        sys.exit(f"{step_name}: no build stamp - run `inject` first.")
    cur = current_inputs()
    drift = [k for k in ("pristine", "batch_size", "batch_mtime", "font_face")
             if stamp.get(k) != cur[k]]
    if drift:
        sys.exit(f"{step_name}: build/DataEN is STALE - {', '.join(drift)} changed since "
                 f"it was built ({stamp.get('built_at')}). Re-run `inject` first.\n"
                 "  (A gate that reads batch.json and the pristine tree will pass while "
                 "the built tree still holds the previous run.)")
    missing = [s for s in needs if s not in (stamp.get("steps") or [])]
    if missing:
        sys.exit(f"{step_name}: build/DataEN has not had {missing} run on it yet.")
    return stamp


def add_step(name):
    stamp = read_stamp() or {}
    steps = list(stamp.get("steps") or [])
    if name not in steps:
        steps.append(name)
    write_stamp(steps)


# --------------------------------------------------------------------------
# steps
# --------------------------------------------------------------------------
def cmd_import():
    print("== mt-import ==")
    # SAME files, SAME order as the export - see export_order().
    run([WOLF, "mt-import", BATCH] + export_order())
    print("== names-fill (copy glossary names onto exact-match lines) ==")
    run([WOLF, "names-fill", os.path.join(OUT, "names.json")] + extract_jsons())
    print("== names-check ==")
    rc, out = run([WOLF, "names-check", os.path.join(OUT, "names.json")] + extract_jsons(),
                  check=False)
    if rc == 2:
        print("  ! names-check reported conflicts (exit 2). Fix them in out/*.json "
              "before injecting - a divergent name breaks by-name DB lookups.")
    print("== layout-restore (rebuild dropped positional whitespace where unambiguous) ==")
    run([WOLF, "layout-restore"] + extract_jsons(), check=False)
    return 0


def cmd_inject():
    print("== inject: pristine -> build/DataEN ==")
    if os.path.exists(DATAEN):
        shutil.rmtree(DATAEN)
    os.makedirs(BUILD, exist_ok=True)
    shutil.copytree(PRISTINE, DATAEN)

    # 1. strings, per file, against the PRISTINE base
    pairs = [(os.path.join(OUT, "CommonEvent.json"), "BasicData/CommonEvent.dat"),
             (os.path.join(OUT, "GameDat.json"), "BasicData/Game.dat")]
    for db in DB_PROJECTS:
        pairs.append((os.path.join(OUT, db + ".json"), f"BasicData/{db}.project"))
    for mps in sorted(glob.glob(os.path.join(PRISTINE, "MapData", "*.mps"))):
        stem = os.path.splitext(os.path.basename(mps))[0]
        pairs.append((os.path.join(OUT, f"map_{stem}.json"), f"MapData/{stem}.mps"))

    applied = skipped = drifted = 0
    for js, rel in pairs:
        if not os.path.exists(js):
            print(f"  ! missing {js} - skipping {rel}")
            continue
        base = os.path.join(PRISTINE, rel.replace("/", os.sep))
        dst = os.path.join(DATAEN, rel.replace("/", os.sep))
        rc, out = run([WOLF, "strings-inject", js, "--base", base, "-o", dst, "--en-punct"],
                      check=False, quiet=True)
        m = re.search(r"applied (\d+)", out)
        if m:
            applied += int(m.group(1))
        for pat, acc in ((r"(\d+) skipped", "s"), (r"(\d+) drifted", "d")):
            mm = re.search(pat, out)
            if mm:
                if acc == "s":
                    skipped += int(mm.group(1))
                else:
                    drifted += int(mm.group(1))
        if rc not in (0, 2):
            sys.exit(f"strings-inject failed on {rel} (exit {rc}):\n{out}")
        if "skipped" in out and not re.search(r"\b0 skipped", out):
            print(f"  ! {rel}: {out.strip().splitlines()[-1]}")
    print(f"  strings: {applied} applied, {skipped} guard-skipped, {drifted} drifted")
    if drifted:
        print("  ! drifted means the base no longer holds `source` - rebase, do NOT re-extract "
              "(re-extracting the whole JSON throws away every translation).")

    # 2. names LAST, in place over the string-injected copy
    print("== inject: names (in place, over the string-injected tree) ==")
    run([WOLF, "names-inject", os.path.join(OUT, "names.json"),
         "--data", DATAEN, "--en-punct"], check=False)

    write_stamp(["inject"])
    print(f"  stamped {STAMP}")
    return 0


def cmd_font():
    require_fresh("font", ["inject"])
    print("== font: repoint Game.dat at a face GDI actually resolves ==")
    gd = os.path.join(DATAEN, "BasicData", "Game.dat")
    js = os.path.join(BUILD, "gamedat.json")
    run([WOLF, "gamedat-json", gd, "-o", js])
    with open(js, encoding="utf-8") as f:
        doc = json.load(f)
    before = doc.get("Font")
    doc["Font"] = FONT_FACE
    with open(js, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"  Font: {before!r} -> {FONT_FACE!r}")
    run([WOLF, "gamedat-apply", js, "--base", gd, "-o", gd])
    print("== font-check (proves the face resolves AND covers the corpus) ==")
    run([WOLF, "font-check", gd, "--corpus", DATAEN], check=False)
    add_step("font")
    return 0


# The message box, measured off the shipped Japanese and then CENSUSED rather than
# maxed. `--width auto` takes the widest JP line it can find and returned 88, which
# put English off the right edge of the screen (reported from a screenshot).
#
# The max is the wrong statistic because the author overflows his own box. Counting
# DISTINCT source strings per line width over 85,503 message lines - sentinels
# expanded, so a hand-paginated line is measured as the two lines it draws as:
#
#     cells  66  68  70  72  74  76 | 78  80  86
#     lines 360 330 162 522  46 133 |  12   1  12
#   distinct 37  30  32  15  10   4 |   1   1   1
#
# a smooth decay to 76 and then a cliff: beyond it the WHOLE corpus holds three
# distinct strings, each repeated, each shipped clipped in the Japanese original.
# (The line counts are inflated by the 9.7x dedup - 15 distinct strings account for
# all 522 lines at 72 - which is why they are read as distinct, not as lines.) So
# the box is 76 cells and `auto` was measuring the author's own overflow.
#
# Nothing here is drawn at a reduced size: the sentinel legend carries no \f[N] at
# all, so there is no smaller-font branch that could legitimately hold 86 cells.
BOX_CELLS = "76"


def cmd_relayout():
    require_fresh("relayout", ["inject"])
    print("== relayout: reflow EN to the box geometry measured from the JP corpus ==")
    # --orig still points at the untranslated tree: max-rows and the \cself insert
    # budget are measured from the game's own Japanese. Only --width is pinned.
    run([WOLF, "relayout", DATAEN, "-o", DATAEN,
         "--width", BOX_CELLS, "--width-face", BOX_CELLS, "--max-rows", "auto",
         "--orig", PRISTINE], check=False)
    print("== desc-relayout: fixed description boxes (cannot page-split) ==")
    for db in DB_PROJECTS:
        cur = os.path.join(DATAEN, "BasicData", db + ".project")
        orig = os.path.join(PRISTINE, "BasicData", db + ".project")
        if os.path.exists(cur):
            run([WOLF, "desc-relayout", cur, "--width", "auto", "--max-lines", "0",
                 "--orig", orig, "-o", cur], check=False)
    print("== normalize-symbols: fold the fullwidth punctuation the extractor skipped ==")
    # strings-extract deliberately skips symbol-only rows (・・・, ！？, ＜…＞), so
    # --en-punct never reaches them and they tofu in a Latin window font.
    run([WOLF, "normalize-symbols", DATAEN, "-o", DATAEN], check=False)
    add_step("relayout")
    return 0


# The author opens a continuation line with one 　 to align it under the opening
# 「. English opens with a halfwidth `"`, so on screen that pad is a two-cell indent
# under a half-cell mark - reported from a screenshot, and 8,433 lines carried it.
#
# It cannot be removed upstream. `wolf relayout`'s deliberate_row() is
# `blank || code-only || starts_with('　')`: the pad is the author's "keep this
# break" marker, and a message without one has ALL its rows merged and refilled to
# the full box width. Stripping it in the store reflowed a message the author broke
# at 26/42/42 cells into one 76-cell line running under that scene's portrait.
#
# So it is stripped HERE, from the built tree, after relayout has consumed it. The
# edit only ever makes a line narrower, so no width or row budget can be violated by
# it, and it goes back through `strings-inject` - the same guarded path as the
# translation itself - rather than editing bytes.
_ROW_PAD_RE = re.compile(r"^[　 ]+")


def _deindent(text):
    """Drop the JP alignment pad from continuation lines of one built message."""
    lines = text.split("\n")
    # A block whose FIRST line is itself indented is a column skeleton, not
    # dialogue - the \v[] status card, " [Scarlet]\n \s[4]", "\n Left x \cself[11]"
    # - and its pads are load-bearing.
    if len(lines) < 2 or not lines[0] or lines[0][0] in " 　":
        return text
    out = list(lines)
    for j in range(1, len(out)):
        m = _ROW_PAD_RE.match(out[j])
        # ASCII-only runs are left alone: they are not relayout's marker, so a
        # surviving one is a pad somebody meant, not the convention being removed.
        if not m or "　" not in m.group(0):
            continue
        out[j] = out[j][len(m.group(0)):]
    return "\n".join(out)


def cmd_deindent():
    require_fresh("deindent", ["inject"])
    print("== deindent: drop the JP alignment pad relayout needed but English does not ==")
    tmp = os.path.join(BUILD, "_deindent")
    if os.path.exists(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp)
    targets = [os.path.join(DATAEN, "BasicData", "CommonEvent.dat")]
    targets += sorted(glob.glob(os.path.join(DATAEN, "MapData", "*.mps")))
    files = changed = lines_fixed = 0
    for i, t in enumerate(targets):
        js = os.path.join(tmp, "%03d.json" % i)
        rc, _out = run([WOLF, "strings-extract", t, "-o", js], check=False, quiet=True)
        if rc != 0 or not os.path.exists(js):
            continue
        with open(js, encoding="utf-8") as f:
            doc = json.load(f)
        n = 0
        stack = [doc]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                s = node.get("source")
                if isinstance(s, str) and isinstance(node.get("text"), str):
                    fixed = _deindent(s)
                    if fixed != s:
                        node["text"] = fixed
                        n += sum(1 for a, b in zip(s.split("\n"), fixed.split("\n"))
                                 if a != b)
                    else:
                        node["text"] = s
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
        if not n:
            continue
        with open(js, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        rc, out = run([WOLF, "strings-inject", js, "--base", t, "-o", t],
                      check=False, quiet=True)
        if rc not in (0, 2):
            sys.exit("deindent: strings-inject failed on %s (exit %d):\n%s" % (t, rc, out))
        if "skipped" in out and not re.search(r"\b0 skipped", out):
            print("  ! %s: %s" % (os.path.basename(t), out.strip().splitlines()[-1]))
        files += 1
        changed += 1
        lines_fixed += n
    print("  deindent: %d line(s) in %d file(s)" % (lines_fixed, files))
    shutil.rmtree(tmp, ignore_errors=True)
    add_step("deindent")
    return 0


def cmd_verify():
    require_fresh("verify", ["inject"])
    print("== verify-roundtrip (binary drift) ==")
    run([WOLF, "verify-roundtrip", "--corpus", DATAEN], check=False)
    print("== verify-semantic (by-name lookups that roundtrip cannot see) ==")
    base = os.path.join(BUILD, "semantic-baseline.txt")
    if not os.path.exists(base):
        print(f"  first run: snapshotting the ORIGINAL's pre-existing danglers to {base}")
        run([WOLF, "verify-semantic", PRISTINE, "--baseline", base], check=False)
    run([WOLF, "verify-semantic", DATAEN, "--baseline", base], check=False)
    print("  (only the DELTA means anything - stock JP games ship name mismatches, and "
          "index-mode ops carry their name as a dead annotation.)")
    print("== residual Japanese in the SHIPPED tree ==")
    _sweep_shipped()
    add_step("verify")
    return 0


_JP = re.compile(r"[぀-ゟ゠-ヺ一-鿿]")


def _sweep_shipped():
    """Re-extract the BUILT tree and look for Japanese.

    This inherits the extractor's blind spot by construction - a field that was
    unreachable going in is unreachable coming out - so it is a floor, not a proof.
    The real gate is playing the game.
    """
    tmp = os.path.join(BUILD, "_sweep")
    if os.path.exists(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp)
    targets = [os.path.join(DATAEN, "BasicData", "CommonEvent.dat"),
               os.path.join(DATAEN, "BasicData", "Game.dat")]
    targets += [os.path.join(DATAEN, "BasicData", d + ".project") for d in DB_PROJECTS]
    targets += sorted(glob.glob(os.path.join(DATAEN, "MapData", "*.mps")))
    total = jp = 0
    worst = []
    for i, t in enumerate(targets):
        o = os.path.join(tmp, f"{i:03d}.json")
        rc, _ = run([WOLF, "strings-extract", t, "-o", o], check=False, quiet=True)
        if rc != 0 or not os.path.exists(o):
            continue
        with open(o, encoding="utf-8") as f:
            doc = json.load(f)
        stack = [doc]
        while stack:
            n = stack.pop()
            if isinstance(n, dict):
                if "source" in n and isinstance(n.get("source"), str):
                    total += 1
                    if _JP.search(n["source"]):
                        jp += 1
                        if len(worst) < 20:
                            worst.append((os.path.basename(t), n["source"][:70]))
                stack.extend(n.values())
            elif isinstance(n, list):
                stack.extend(n)
    print(f"  shipped units: {total}, still containing Japanese: {jp}")
    for f, s in worst:
        print(f"   - {f}: {s!r}")
    shutil.rmtree(tmp, ignore_errors=True)


def cmd_deploy():
    stamp = require_fresh("deploy", ["inject"])
    for want in ("font", "relayout", "verify"):
        if want not in stamp.get("steps", []):
            print(f"  ! `{want}` has not been run on this tree.")
    print(f"== deploy: build/DataEN -> {GAME}\\Data ==")
    for sub in ("BasicData", "MapData"):
        src = os.path.join(DATAEN, sub)
        dst = os.path.join(GAME, "Data", sub)
        if not os.path.isdir(dst):
            sys.exit(f"deploy: {dst} does not exist - is SCARLET_GAME_DIR right?")
        # MIRROR, not merge: delete the deployed set first. Copying never deletes,
        # so a file dropped from the payload survives in the game folder and keeps
        # being loaded while every gate stays green.
        shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print(f"  mirrored {sub}")
    print("  The engine reads the loose Data/ folder before Data.wolf, so this is live.")
    print("  Test: launch, load a save, open EVERY menu, walk the maps you changed, "
          "save and reload.")
    return 0


def cmd_restore():
    print(f"== restore: pristine -> {GAME}\\Data ==")
    for sub in ("BasicData", "MapData"):
        dst = os.path.join(GAME, "Data", sub)
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(os.path.join(PRISTINE, sub), dst)
        print(f"  restored {sub}")
    return 0


def cmd_all():
    for fn in (cmd_import, cmd_inject, cmd_font, cmd_relayout, cmd_deindent, cmd_verify):
        print()
        fn()
    print("\nBuild complete. Review the sweep above, then: python scripts/build.py deploy")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["import", "inject", "font", "relayout", "deindent",
                                     "verify", "deploy", "restore", "all"])
    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if not os.path.exists(WOLF):
        sys.exit(f"wolf.exe not found at {WOLF} - set WOLF_EXE.")
    return {
        "import": cmd_import, "inject": cmd_inject, "font": cmd_font,
        "relayout": cmd_relayout, "deindent": cmd_deindent,
        "verify": cmd_verify, "deploy": cmd_deploy,
        "restore": cmd_restore, "all": cmd_all,
    }[args.step]()


if __name__ == "__main__":
    sys.exit(main() or 0)
