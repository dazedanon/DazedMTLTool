"""Prototype of `wolf font-check`: diagnose a Game.dat Font face that GDI cannot
resolve.

WHY this tool exists: a Font value with a trailing style word (e.g. "源暎ラテミン
v2 Medium") is passed verbatim to GDI CreateFontW, which does NOT strip style
suffixes. When no installed face matches the full string GDI silently falls back
to a generic bitmap face (MS Sans Serif), and every CJK/symbol glyph renders as
tofu with zero error. This tool resolves the face the way the game will, then
probes actual glyph coverage so the trap is visible before shipping.
"""
import argparse
import ctypes
import glob
import os
import sys
import unicodedata

from wolfscript import WOLF_CODE_RE, iter_display_literals, load_json, read_text

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Conventional default: a `wolf gamedat-json` dump in the working dir. Pass
# --font or --gamedat-json to point elsewhere.
DEFAULT_GAMEDAT = "gamedat.json"

# Generic faces GDI substitutes when the requested name does not resolve.
GENERIC_FALLBACKS = {"MS Sans Serif", "Microsoft Sans Serif", "System",
                     "Fixedsys", "Terminal"}

# Installed-by-default CJK faces we can recommend without asking the user to
# install anything.
SUGGESTED = ["ＭＳ ゴシック", "Yu Gothic"]

DEFAULT_GLYPHS = "★☆※●■◆▲▼①②♪♡♥é¥・：？％＜＞～→…×行動力歌唱残個数所持"

GGI_MARK_NONEXISTING_GLYPHS = 1

gdi32 = ctypes.windll.gdi32
user32 = ctypes.windll.user32


def _fold(name):
    """Normalize a face name for alias comparison. NFKC folds fullwidth Latin
    (the "ＭＳ ..." aliases) down to ASCII so the requested alias matches the
    canonical name GDI returns. Case and surrounding space are ignored too."""
    return unicodedata.normalize("NFKC", name).casefold().strip()


def resolve_face(face):
    """Return the face name GDI actually selects for `face`, mirroring the
    game's own CreateFontW call so a style-suffix mismatch surfaces here."""
    hf = gdi32.CreateFontW(-16, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, face)
    hdc = user32.GetDC(0)
    old = gdi32.SelectObject(hdc, hf)
    buf = ctypes.create_unicode_buffer(64)
    gdi32.GetTextFaceW(hdc, 64, buf)
    resolved = buf.value
    gdi32.SelectObject(hdc, old)
    user32.ReleaseDC(0, hdc)
    gdi32.DeleteObject(hf)
    return resolved


def missing_glyphs(face, chars):
    """Return the subset of `chars` with no glyph in the resolved face. Uses the
    same -16px CreateFontW so coverage matches what resolve_face reported."""
    hf = gdi32.CreateFontW(-16, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, face)
    hdc = user32.GetDC(0)
    old = gdi32.SelectObject(hdc, hf)
    missing = []
    idx = ctypes.c_ushort(0)
    for ch in chars:
        gdi32.GetGlyphIndicesW(hdc, ch, 1, ctypes.byref(idx),
                               GGI_MARK_NONEXISTING_GLYPHS)
        if idx.value == 0xFFFF:
            missing.append(ch)
    gdi32.SelectObject(hdc, old)
    user32.ReleaseDC(0, hdc)
    gdi32.DeleteObject(hf)
    return missing


def harvest_corpus(corpus_dir):
    """Distinct non-ASCII display chars across every *.wscript in the corpus,
    with control codes stripped so we probe only rendered glyphs."""
    seen = set()
    for path in glob.glob(os.path.join(corpus_dir, "*.wscript")):
        text = read_text(path)
        for _lno, _cmd, lit in iter_display_literals(text):
            for ch in WOLF_CODE_RE.sub("", lit):
                if ord(ch) > 0x7F:
                    seen.add(ch)
    return "".join(sorted(seen))


def main():
    ap = argparse.ArgumentParser(
        description="Diagnose a Game.dat Font face GDI cannot resolve (the "
                    "style-suffix tofu trap).")
    ap.add_argument("--font", help="Face name to test. Defaults to the Font "
                                    "field of --gamedat-json.")
    ap.add_argument("--gamedat-json", default=None,
                    help="Game.dat dump to read the Font field from.")
    ap.add_argument("--corpus", default=None,
                    help="Directory of *.wscript files to harvest test glyphs "
                         "from. Falls back to a built-in glyph set.")
    args = ap.parse_args()

    face = args.font
    if not face:
        gamedat = args.gamedat_json or DEFAULT_GAMEDAT
        face = load_json(gamedat).get("Font", "")
        if not face:
            print(f"ERROR: no Font field in {gamedat}")
            return 2

    print(f"Requested face: {face!r}")

    resolved = resolve_face(face)
    print(f"GDI resolved to: {resolved!r}")

    if args.corpus:
        chars = harvest_corpus(args.corpus)
        source = f"corpus {args.corpus}"
        if not chars:
            chars = DEFAULT_GLYPHS
            source = "built-in default (corpus yielded nothing)"
    else:
        chars = DEFAULT_GLYPHS
        source = "built-in default"

    # GDI never fails CreateFontW: an unmatched name is silently swapped for a
    # generic bitmap face (MS Sans Serif) or the default GUI face (Arial), which
    # is the style-suffix trap. But GDI also returns the canonical localized
    # name of a face that DID match (requesting the fullwidth alias "ＭＳ ゴ
    # シック" resolves to "MS Gothic"), so a bare string mismatch is not proof
    # of failure. Drift onto a generic fallback is always a miss. Other drift is
    # a miss only when the names are not the same alias AND glyphs are absent.
    generic = resolved in GENERIC_FALLBACKS
    same_alias = _fold(resolved) == _fold(face)

    print()
    print(f"Glyph test ({len(chars)} chars from {source}):")
    missing = missing_glyphs(face, chars)
    print(f"  missing: {len(missing)} / {len(chars)}")
    if missing:
        print(f"  missing chars: {''.join(missing)}")

    unresolved = generic or (not same_alias and bool(missing))
    if unresolved:
        print()
        print("=" * 60)
        print("WARNING: the requested face did NOT resolve.")
        if generic:
            print(f"  GDI fell back to the generic face {resolved!r}.")
        else:
            print(f"  GDI substituted a different face {resolved!r}.")
        print("  This is the style-suffix trap: CreateFontW does not strip a")
        print("  trailing style word (e.g. ' Medium', ' v2'), so the full")
        print("  string matches no installed face and every CJK/symbol glyph")
        print("  renders as tofu with no error.")
        print("=" * 60)

    problems = unresolved or bool(missing)
    if problems:
        print()
        print("SUGGESTED fallbacks (installed by default, no install needed):")
        for name in SUGGESTED:
            print(f"  - {name!r}")
        return 1

    print()
    print("OK: face resolves and all probed glyphs are present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
