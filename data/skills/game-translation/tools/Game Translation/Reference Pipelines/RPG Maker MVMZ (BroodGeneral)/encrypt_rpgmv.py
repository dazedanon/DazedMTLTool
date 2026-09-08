"""
encrypt_rpgmv.py — re-encrypt translated PNGs back to RPG Maker MV .rpgmvp
and replace the originals in www/img (after backing them up).

Reverse of decrypt_rpgmv.py:
  encrypt = XOR the PNG's first 16 bytes with KEY, then prepend the 16-byte
  MV fake header.

Source PNGs: imagestranslated/  (flat folder)
Targets:     www/img/<subdir>/<name>.rpgmvp  (resolved by basename, with
             explicit overrides for ambiguous / renamed files)
Backups:     www/img_backup_<timestamp>/<subdir>/<name>.rpgmvp
"""
import os
import sys
import shutil

KEY = bytes.fromhex("41482469aa2d1ec391fedd5a2f25b744")
HEADER = bytes.fromhex("5250474d560000000003010000000000")  # RPGMV MV header
HEADER_LEN = 16

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRANS = os.path.join(ROOT, "imagestranslated")
IMG = os.path.join(ROOT, "www", "img")

# Explicit overrides: translated-png-basename -> rel path under www/img (no ext).
# Needed where the translated name differs from the asset name, or the basename
# exists in multiple subdirs. A value may be a single rel-path OR a list of
# rel-paths when the same translated art must replace several copies.
OVERRIDES = {
    "m0267": "pictures/Material0267",
    "m0273": "pictures/Material0273",
    # m_6a/m_6b name plates live in BOTH layers/ and pictures/ (same plate art,
    # only the text differs). The game shows the PICTURES copy for the in-dialogue
    # name plate, so BOTH must get the translation or the plate stays Japanese.
    "m_6a":  ["layers/m_6a", "pictures/m_6a"],
    "m_6b":  ["layers/m_6b", "pictures/m_6b"],
}


def build_index():
    idx = {}
    for r, _d, fs in os.walk(IMG):
        for f in fs:
            if f.lower().endswith(".rpgmvp"):
                idx.setdefault(os.path.splitext(f)[0], []).append(os.path.join(r, f))
    return idx


def encrypt_bytes(png: bytes) -> bytes:
    body = bytearray(png)
    for i in range(min(HEADER_LEN, len(body))):
        body[i] ^= KEY[i]
    return HEADER + bytes(body)


def main():
    apply = "--apply" in sys.argv
    stamp = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--stamp=")), "manual")
    idx = build_index()
    backup_root = os.path.join(ROOT, "www", f"img_backup_{stamp}")

    plan, problems = [], []
    for f in sorted(os.listdir(TRANS)):
        if not f.lower().endswith(".png"):
            continue
        base = os.path.splitext(f)[0]
        if base in OVERRIDES:
            rels = OVERRIDES[base]
            if isinstance(rels, str):
                rels = [rels]
            targets = [os.path.join(IMG, r.replace("/", os.sep) + ".rpgmvp") for r in rels]
        else:
            m = idx.get(base, [])
            if len(m) == 1:
                targets = [m[0]]
            else:
                problems.append((f, "NO MATCH" if not m else "AMBIGUOUS: " + ", ".join(m)))
                continue
        for target in targets:
            plan.append((os.path.join(TRANS, f), target))

    print(f"{len(plan)} files to encrypt+replace; {len(problems)} problems.")
    for src, tgt in plan:
        print(f"  {os.path.basename(src):26s} -> {os.path.relpath(tgt, ROOT)}")
    for f, why in problems:
        print(f"  !! {f}: {why}")

    if not apply:
        print("\nDRY RUN. Re-run with --apply to write (originals backed up first).")
        return
    if problems:
        print("\nRefusing to apply while there are unresolved problems.")
        return

    done = 0
    for src, tgt in plan:
        rel = os.path.relpath(tgt, IMG)
        bpath = os.path.join(backup_root, rel)
        os.makedirs(os.path.dirname(bpath), exist_ok=True)
        if os.path.exists(tgt):
            shutil.copy2(tgt, bpath)
        with open(src, "rb") as fh:
            png = fh.read()
        with open(tgt, "wb") as fh:
            fh.write(encrypt_bytes(png))
        done += 1
    print(f"\nReplaced {done} .rpgmvp files. Backups in {os.path.relpath(backup_root, ROOT)}/")


if __name__ == "__main__":
    main()
