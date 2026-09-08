# -*- coding: utf-8 -*-
"""
build_patch.py — assemble a DROP-IN English patch for a fresh **Brood General
Succubus** (サキュバス将軍の兵力増産所, RPG Maker MZ) folder. Copies only the files
the translation changed, mirroring the game's MZ layout (`data/`, `js/`, `img/`),
into dist/BroodGeneralSuccubus_EN_patch/ (+ a README and the save converter).

A user with a clean copy drops the patch's folders over theirs.

Prereq: run `python tooling/tl.py inject --in-place` first — it patches `data/`
and leaves a `data_backup_<timestamp>/` of the original JP, which this script
diffs against to find exactly which files changed.

NOTE (MZ): images are encrypted as `.png_`/`.ogg_` and plugin strings live in
`js/plugins.js` + `js/plugins/*.js`. Those passes aren't done yet — add the
translated relative paths to IMAGES / PLUGINS below once they are, and they'll
be folded into the patch.
"""
import os, sys, glob, shutil, filecmp, zipfile

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dist", "BroodGeneralSuccubus_EN_patch")

# MZ encrypted images use the `.png_` extension. The set of images we re-injected
# is discovered automatically: it's the union of every img_backup_*/ dir (each holds
# the pre-injection original of a file we touched); we ship their current img/ form.
IMG_EXT = ".png_"

# Player-facing translated plugin files, relative to js/.
PLUGINS = ["plugins.js"]


def copy(src, rel):
    dst = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def main():
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)

    # 1. data: only json that differs from the original JP backup
    backups = sorted(glob.glob(os.path.join(ROOT, "data_backup_*")))
    if not backups:
        sys.exit("No data_backup_* found. Run `python tooling/tl.py inject --in-place` first.")
    jp = backups[-1]
    data_changed = []
    for f in glob.glob(os.path.join(ROOT, "data", "*.json")):
        bn = os.path.basename(f)
        bf = os.path.join(jp, bn)
        if not os.path.exists(bf) or not filecmp.cmp(f, bf, shallow=False):
            copy(f, f"data/{bn}")
            data_changed.append(bn)

    # 2. plugins (js) — optional
    miss = []
    for rel in PLUGINS:
        src = os.path.join(ROOT, "js", rel)
        copy(src, f"js/{rel}") if os.path.exists(src) else miss.append(f"js/{rel}")

    # 3. images (.png_): every file we re-injected = union of the img_backup_* dirs,
    #    shipped in their current (translated) img/ form.
    touched = set()
    for d in glob.glob(os.path.join(ROOT, "img_backup_*")):
        for f in glob.glob(os.path.join(d, "**", "*" + IMG_EXT), recursive=True):
            touched.add(os.path.relpath(f, d))
    img_ok = 0
    for rel in sorted(touched):
        src = os.path.join(ROOT, "img", rel)
        if os.path.exists(src):
            copy(src, os.path.join("img", rel)); img_ok += 1
        else:
            miss.append(os.path.join("img", rel))

    # 3b. package.json (NW.js window title — translator credit shown at launch)
    pkg = os.path.join(ROOT, "package.json")
    if os.path.exists(pkg):
        copy(pkg, "package.json")

    # 4. save converter (optional tools/)
    os.makedirs(os.path.join(OUT, "tools"), exist_ok=True)
    for t in ("translate_save.py",):
        s = os.path.join(ROOT, "tooling", t)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(OUT, "tools", t))

    # 5. README
    readme = """# Brood General Succubus — English Patch

English translation for **サキュバス将軍の兵力増産所**.

## Install

1. Back up your game's `data` folder (and `js`/`img` if this patch includes them).
2. Copy this patch's folders into your game, **overwrite** when asked.
3. Play. It's in English now.

## Old Japanese saves? (optional)

```
python tools/translate_save.py --apply
```

New games are already in English.
"""
    open(os.path.join(OUT, "README.md"), "w", encoding="utf-8").write(readme)

    # 6. zip it up (zip root == data/ js/ img/ README so it extracts onto the game folder)
    zip_path = OUT + ".zip"
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, files in os.walk(OUT):
            for fn in files:
                full = os.path.join(base, fn)
                z.write(full, os.path.relpath(full, OUT))
    size_mb = os.path.getsize(zip_path) / (1024 * 1024)

    print(f"PATCH built at: {os.path.relpath(OUT, ROOT)}")
    print(f"  data json : {len(data_changed)}")
    print(f"  plugins   : {len(PLUGINS)} (plugins.js)")
    print(f"  images    : {img_ok}")
    print(f"  zip       : {os.path.relpath(zip_path, ROOT)}  ({size_mb:.1f} MB)")
    if miss:
        print("  !! MISSING:", miss)


if __name__ == "__main__":
    main()
