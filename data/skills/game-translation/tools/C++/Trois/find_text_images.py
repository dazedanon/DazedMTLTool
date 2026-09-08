#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
find_text_images.py — find images containing text of a given script (e.g. Japanese,
including vertical) and collect them into an output folder.

Nothing is hard-coded: input paths, output folder, OCR backend, the target Unicode
scripts, thresholds, file extensions and the collect action are all CLI options.
The OCR engine is a pluggable adapter; "Japanese detection" is just the default set
of Unicode script ranges, so the same tool finds Korean, Cyrillic, Latin, etc.

Examples
--------
# Japanese (default), copy hits into ./jp_images, keeping folder structure:
python find_text_images.py natuiso_extracted -o jp_images

# Several input roots, move instead of copy, write a manifest:
python find_text_images.py dirA dirB -o out --action move --manifest hits.csv

# Detect Korean instead, require at least 3 matching chars:
python find_text_images.py imgs -o out --scripts hangul --min-chars 3

Backends
--------
  easyocr   : pip install easyocr            (default; supports Japanese)
  tesseract : needs tesseract.exe + pip install pytesseract
              language data 'jpn' and 'jpn_vert' for vertical Japanese
"""

import os
import sys
import csv
import json
import shutil
import argparse
import datetime
from fnmatch import fnmatch

# --------------------------------------------------------------------------
# Unicode script ranges (extend freely — this is what makes it reusable)
# --------------------------------------------------------------------------
SCRIPT_RANGES = {
    "hiragana":  [(0x3041, 0x309F)],
    "katakana":  [(0x30A0, 0x30FF), (0x31F0, 0x31FF), (0xFF66, 0xFF9D)],  # + halfwidth
    "kanji":     [(0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF),
                  (0x20000, 0x2A6DF)],
    "han":       [(0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF),
                  (0x20000, 0x2A6DF)],
    "cjk_punct": [(0x3000, 0x303F), (0xFF01, 0xFF60)],  # 、。「」 fullwidth punct
    "hangul":    [(0xAC00, 0xD7A3), (0x1100, 0x11FF), (0x3130, 0x318F)],
    "cyrillic":  [(0x0400, 0x04FF), (0x0500, 0x052F)],
    "latin":     [(0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x024F)],
    "thai":      [(0x0E00, 0x0E7F)],
    "arabic":    [(0x0600, 0x06FF)],
}
# Convenience groups
SCRIPT_GROUPS = {
    "japanese": ["hiragana", "katakana", "kanji"],
    "ja":       ["hiragana", "katakana", "kanji"],
    "chinese":  ["han"],
    "korean":   ["hangul"],
}

DEFAULT_EXTS = [".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tga", ".webp", ".tif", ".tiff"]


def resolve_scripts(tokens):
    """Expand a list of script/group names into a flat list of (lo, hi) ranges."""
    names = []
    for tok in tokens:
        tok = tok.strip().lower()
        if tok in SCRIPT_GROUPS:
            names.extend(SCRIPT_GROUPS[tok])
        elif tok in SCRIPT_RANGES:
            names.append(tok)
        else:
            raise SystemExit("unknown script/group %r (known: %s)"
                             % (tok, ", ".join(sorted(set(SCRIPT_RANGES) | set(SCRIPT_GROUPS)))))
    ranges = []
    for n in names:
        ranges.extend(SCRIPT_RANGES[n])
    return names, ranges


def count_in_ranges(text, ranges):
    n = 0
    for ch in text:
        cp = ord(ch)
        for lo, hi in ranges:
            if lo <= cp <= hi:
                n += 1
                break
    return n


# --------------------------------------------------------------------------
# OCR backends (pluggable). Each .read(path) -> list of (text, confidence)
# --------------------------------------------------------------------------
class EasyOcrBackend:
    name = "easyocr"

    def __init__(self, langs, gpu=False, max_dim=2000, rotations=None, min_conf=0.0,
                 mag_ratio=1.6):
        import easyocr  # lazy
        import numpy as np  # noqa
        self.np = __import__("numpy")
        self.cv2 = __import__("cv2")
        self.reader = easyocr.Reader(langs, gpu=gpu, verbose=False)
        self.max_dim = max_dim
        self.rotations = rotations or []  # e.g. [90, 270]; OFF by default — it
        # significantly HURTS recall on stylized/dense horizontal text (logos).
        self.min_conf = min_conf
        self.mag_ratio = mag_ratio  # >1 upscales internally -> better small/stylized recall

    def _load(self, path):
        cv2, np = self.cv2, self.np
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)  # unicode-safe
        if img is None:
            from PIL import Image
            img = np.array(Image.open(path).convert("RGB"))[:, :, ::-1].copy()
        if self.max_dim:
            h, w = img.shape[:2]
            m = max(h, w)
            if m > self.max_dim:
                s = self.max_dim / m
                img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        return img

    def read(self, path):
        img = self._load(path)
        kw = {"mag_ratio": self.mag_ratio}
        if self.rotations:
            kw["rotation_info"] = list(self.rotations)
        out = []
        for (_box, text, conf) in self.reader.readtext(img, detail=1, paragraph=False, **kw):
            if conf >= self.min_conf:
                out.append((text, float(conf)))
        return out


class TesseractBackend:
    name = "tesseract"

    def __init__(self, langs, max_dim=0, min_conf=0.0, tess_cmd=None):
        import pytesseract  # lazy
        self.pt = pytesseract
        if tess_cmd:
            pytesseract.pytesseract.tesseract_cmd = tess_cmd
        # tesseract wants '+'-joined langs, e.g. 'jpn+jpn_vert'
        self.lang = "+".join(langs)
        self.max_dim = max_dim
        self.min_conf = min_conf  # 0..1 (tesseract reports 0..100)

    def read(self, path):
        from PIL import Image
        img = Image.open(path)
        if self.max_dim:
            m = max(img.size)
            if m > self.max_dim:
                s = self.max_dim / m
                img = img.resize((int(img.size[0] * s), int(img.size[1] * s)))
        data = self.pt.image_to_data(img, lang=self.lang, output_type=self.pt.Output.DICT)
        out = []
        for text, conf in zip(data["text"], data["conf"]):
            try:
                c = float(conf) / 100.0
            except (TypeError, ValueError):
                c = 0.0
            if text and text.strip() and c >= self.min_conf:
                out.append((text, c))
        return out


def make_backend(args):
    backend = args.backend
    if backend == "auto":
        import importlib.util as u
        if u.find_spec("easyocr"):
            backend = "easyocr"
        elif u.find_spec("pytesseract"):
            backend = "tesseract"
        else:
            raise SystemExit("No OCR backend available. Install one:\n"
                             "  pip install easyocr        (recommended here)\n"
                             "  pip install pytesseract    (+ tesseract.exe, jpn, jpn_vert)")
    if backend == "easyocr":
        if args.gpu:
            try:
                import torch
                if torch.cuda.is_available():
                    if not args.quiet:
                        print("GPU            : %s (CUDA %s)"
                              % (torch.cuda.get_device_name(0), torch.version.cuda))
                else:
                    print("WARNING: --gpu requested but torch.cuda.is_available() is False "
                          "(installed build: %s). Falling back to CPU. Install a CUDA torch:\n"
                          "  pip install --force-reinstall torch torchvision "
                          "--index-url https://download.pytorch.org/whl/cu126"
                          % getattr(torch, "__version__", "?"))
            except Exception as e:
                print("WARNING: could not query CUDA (%s); EasyOCR will decide." % e)
        langs = args.langs or ["ja", "en"]
        rots = [int(x) for x in args.rotations.split(",")] if args.rotations else None
        return EasyOcrBackend(langs, gpu=args.gpu, max_dim=args.max_dim,
                              rotations=rots, min_conf=args.min_conf,
                              mag_ratio=args.mag_ratio)
    if backend == "tesseract":
        langs = args.langs or ["jpn", "jpn_vert"]  # jpn_vert = tesseract's vertical model
        return TesseractBackend(langs, max_dim=args.max_dim, min_conf=args.min_conf,
                                tess_cmd=args.tesseract_cmd)
    raise SystemExit("unknown backend %r" % backend)


# --------------------------------------------------------------------------
# Walking + collecting
# --------------------------------------------------------------------------
def _matches(rel, patterns):
    """True if the forward-slashed relative path (or any of its parts) matches a
    pattern. A bare token like 'bg' matches a directory/file part named 'bg' or a
    path prefix 'bg/...'; globs like 'cg/*' or '*.thumb.png' work too."""
    relposix = rel.replace(os.sep, "/").lower()
    parts = relposix.split("/")
    for raw in patterns:
        p = raw.lower()
        if fnmatch(relposix, p):
            return True
        if p in parts:                       # exact dir/file-part name
            return True
        if relposix.startswith(p.rstrip("/") + "/"):  # path prefix
            return True
    return False


def iter_images(inputs, exts, recursive, exclude=None, include=None):
    exts = {e.lower() for e in exts}
    exclude = exclude or []
    include = include or []
    for root in inputs:
        if os.path.isfile(root):
            if os.path.splitext(root)[1].lower() in exts:
                yield root, os.path.basename(root)
            continue
        for dirpath, dirs, files in os.walk(root):
            # prune excluded directories so we never descend into them
            if exclude:
                dirs[:] = [d for d in dirs
                           if not _matches(os.path.relpath(os.path.join(dirpath, d), root), exclude)]
            for f in files:
                if os.path.splitext(f)[1].lower() not in exts:
                    continue
                full = os.path.join(dirpath, f)
                rel = os.path.relpath(full, root)
                if exclude and _matches(rel, exclude):
                    continue
                if include and not _matches(rel, include):
                    continue
                yield full, rel
            if not recursive:
                break


def collect(src, out_dir, rel, action, flatten, overwrite):
    if action in ("list", "none"):
        return None
    if flatten:
        dest = os.path.join(out_dir, rel.replace(os.sep, "__"))
    else:
        dest = os.path.join(out_dir, rel)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    if os.path.exists(dest) and not overwrite:
        base, ext = os.path.splitext(dest)
        i = 1
        while os.path.exists("%s_%d%s" % (base, i, ext)):
            i += 1
        dest = "%s_%d%s" % (base, i, ext)
    if action == "copy":
        shutil.copy2(src, dest)
    elif action == "move":
        shutil.move(src, dest)
    elif action == "symlink":
        try:
            os.symlink(os.path.abspath(src), dest)
        except OSError:
            shutil.copy2(src, dest)
    return dest


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="image files or directories to scan")
    ap.add_argument("-o", "--output", default="text_images", help="output folder")
    ap.add_argument("--backend", default="auto", choices=["auto", "easyocr", "tesseract"])
    ap.add_argument("--langs", nargs="*", default=None,
                    help="OCR languages (easyocr: ja en ; tesseract: jpn jpn_vert)")
    ap.add_argument("--scripts", default="japanese",
                    help="comma-separated scripts/groups to require (default: japanese). "
                         "groups: japanese,chinese,korean ; scripts: %s"
                         % ",".join(sorted(SCRIPT_RANGES)))
    ap.add_argument("--min-chars", type=int, default=1,
                    help="minimum matching characters for an image to qualify")
    ap.add_argument("--min-conf", type=float, default=0.0,
                    help="ignore OCR detections below this confidence (0..1). Keep at 0 to "
                         "catch vertical text (EasyOCR reads it at very low confidence but "
                         "still emits Japanese characters); raise it for higher precision "
                         "on horizontal text.")
    ap.add_argument("--rotations", default=None,
                    help="easyocr rotation_info, e.g. '90,270'. OFF by default — it badly "
                         "HURTS recall on stylized/dense horizontal text (logos). Vertical "
                         "Japanese is still flagged via its codepoints without it.")
    ap.add_argument("--mag-ratio", type=float, default=1.6,
                    help="easyocr upscale factor (>1 boosts small/stylized-text recall; default 1.6)")
    ap.add_argument("--max-dim", type=int, default=2400,
                    help="downscale longest side to this before OCR (0 = no resize)")
    ap.add_argument("--gpu", action="store_true", help="use GPU (easyocr) if available")
    ap.add_argument("--ext", nargs="*", default=DEFAULT_EXTS, help="image extensions")
    ap.add_argument("--exclude", nargs="*", default=[],
                    help="skip paths matching these (dir name, path prefix, or glob); "
                         "e.g. --exclude bg cg  or  --exclude 'cg/*' '*_thumb.png'")
    ap.add_argument("--include", nargs="*", default=[],
                    help="if given, ONLY scan paths matching these (same matching as --exclude)")
    ap.add_argument("--action", default="copy",
                    choices=["copy", "move", "symlink", "list", "none"])
    ap.add_argument("--flatten", action="store_true", help="flat output (no subfolders)")
    ap.add_argument("--no-recursive", dest="recursive", action="store_false", default=True)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--manifest", default=None, help="write CSV (or .json) of hits")
    ap.add_argument("--limit", type=int, default=0, help="scan at most N images (debug)")
    ap.add_argument("--tesseract-cmd", default=None, help="path to tesseract.exe")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    # Windows consoles are often cp1252; recognized text/paths may be non-ASCII.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


    script_names, ranges = resolve_scripts(args.scripts.split(","))
    if not args.quiet:
        print("Target scripts : %s" % ", ".join(script_names))
        print("Backend        : %s" % args.backend)

    images = list(iter_images(args.inputs, args.ext, args.recursive,
                              exclude=args.exclude, include=args.include))
    if args.limit:
        images = images[:args.limit]
    if not args.quiet:
        print("Scanning       : %d images" % len(images))

    backend = make_backend(args)
    if not args.quiet:
        print("Loaded backend : %s" % backend.name)

    os.makedirs(args.output, exist_ok=True)
    hits = []
    errors = 0
    for i, (full, rel) in enumerate(images, 1):
        try:
            dets = backend.read(full)
        except Exception as e:
            errors += 1
            if not args.quiet:
                print("  ! %s: %s" % (rel, e))
            continue
        text = " ".join(t for t, _ in dets)
        nchars = count_in_ranges(text, ranges)
        if nchars >= args.min_chars:
            maxconf = max((c for _, c in dets), default=0.0)
            dest = collect(full, args.output, rel, args.action, args.flatten, args.overwrite)
            hits.append({"path": full, "rel": rel, "chars": nchars,
                         "max_conf": round(maxconf, 3),
                         "text": text[:200], "dest": dest})
            if not args.quiet:
                print("  [HIT %4d] %3d chars  %s" % (len(hits), nchars, rel))
        if not args.quiet and i % 100 == 0:
            print("  ... %d/%d scanned, %d hits" % (i, len(images), len(hits)))

    if args.manifest:
        if args.manifest.lower().endswith(".json"):
            with open(args.manifest, "w", encoding="utf-8") as f:
                json.dump(hits, f, ensure_ascii=False, indent=2)
        else:
            with open(args.manifest, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["rel", "chars", "max_conf", "text", "path", "dest"])
                w.writeheader()
                for h in hits:
                    w.writerow(h)

    print("\nDone: %d/%d images contain target text (%d errors). Output -> %s"
          % (len(hits), len(images), errors, os.path.abspath(args.output)))
    if args.manifest:
        print("Manifest: %s" % os.path.abspath(args.manifest))


if __name__ == "__main__":
    main()
