r"""Which characters will draw as a TOFU BOX in the font the game asks for?

    glyph_audit.py [--font "Family Name"] [--show 40]

A missing glyph is invisible to every other check in this pipeline. The text is
correct, the placeholders match, nothing overflows, no Japanese is left - and the
player sees a hollow rectangle. It only surfaces when somebody looks at the
screen and says "there's some tofus".

This is the check that finds it without looking: take the cmap of the font the
game will actually ask for, and diff it against every character the patch ships.

WHY THE FONT NAME MATTERS MORE THAN THE TEXT. `GameSettings.gameFont` names an
INSTALLED system font. Name one the player does not have and the native layer
substitutes something of its own choosing, so the glyph repertoire is decided by
the player's machine rather than by the game. On this game the author asks for
游明朝 Demibold, and the substitute in play had no U+2661 WHITE HEART SUIT - a
character the SOURCE uses 229,107 times.

Swapping the character is not a fix, and this tool shows why: it reports
coverage across the plausible substitutes too, and the likely ones here
(Microsoft YaHei, JhengHei, SimSun) have no ♡, no ♥ and no ♪ either. There is
nothing to fall back to. The answer is to NAME a font that has the glyphs, which
is what `config.game_font_override` does.
"""

import collections
import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from artl import codes, config, store                                # noqa: E402

# Fonts a Windows machine may substitute when the requested family is absent.
# Reported so a "just use a different character" instinct can be checked rather
# than argued about.
SUBSTITUTES = [
    ("Yu Gothic Light", "YuGothL.ttc"), ("Yu Gothic", "YuGothR.ttc"),
    ("MS Gothic", "msgothic.ttc"), ("Microsoft YaHei", "msyh.ttc"),
    ("Microsoft JhengHei", "msjh.ttc"), ("SimSun", "simsun.ttc"),
    ("Segoe UI", "segoeui.ttf"), ("Arial", "arial.ttf"),
]


def cmaps(path):
    from fontTools.ttLib import TTFont, TTCollection
    try:
        fonts = (TTCollection(path).fonts if path.lower().endswith(".ttc")
                 else [TTFont(path, fontNumber=0)])
        out = []
        for f in fonts:
            try:
                c = f.getBestCmap()
                if c:
                    out.append(c)
            except Exception:
                pass
        return out
    except Exception:
        return []


def covered(cs, cp):
    return any(cp in c for c in cs)


def main(*argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = config.load()
    show = int(argv[argv.index("--show") + 1]) if "--show" in argv else 40
    want = (argv[argv.index("--font") + 1] if "--font" in argv
            else (cfg.get("game_font_override") or cfg.get("game_font")))

    from artl import measure
    m = measure.resolve(cfg, cfg.get("layout_font_size", 24))
    cs = cmaps(m.path)
    if not cs:
        print("could not read a cmap from %s" % m.path)
        return 1

    docs = store.load_docs(cfg["store_dir"])
    ship = collections.Counter()
    src = collections.Counter()
    ship_units = collections.Counter()
    for _p, u in store.all_units(docs):
        tl = codes.clean_translation(u.get("tl") or "")
        if tl.strip():
            body = codes.unmask_codes(tl, u.get("codes") or {}, pad_inserts=True)
            for ch in set(body):
                ship_units[ch] += 1
            for ch in body:
                ship[ch] += 1
        for ch in (u.get("raw") or ""):
            src[ch] += 1

    missing = [(c, n) for c, n in ship.items()
               if not covered(cs, ord(c)) and c not in "\r\n\t"]
    missing.sort(key=lambda t: -t[1])

    print("GLYPH AUDIT")
    print("  game asks for : %r" % want)
    print("  measured with : %s" % m.describe())
    print("  characters the patch ships : %d distinct" % len(ship))
    print("  NOT IN THE FONT            : %d distinct, %d occurrences, %d units"
          % (len(missing), sum(n for _c, n in missing),
             sum(ship_units[c] for c, _n in missing)))
    print()
    for c, n in missing[:show]:
        try:
            nm = unicodedata.name(c)
        except ValueError:
            nm = "?"
        print("   U+%04X %r  x%-8d %-40s  (source used it %d times)"
              % (ord(c), c, n, nm[:40], src.get(c, 0)))
    if not missing:
        print("   nothing - every shipped character has a glyph")

    # The characters that matter most are the ones the SOURCE leans on. Show how
    # the plausible substitutes handle them, so "just use another character" can
    # be tested rather than assumed.
    hot = [c for c, n in sorted(src.items(), key=lambda t: -t[1])
           if ord(c) > 0x2000 and n > 100][:8]
    if hot:
        fd = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        print("\n  coverage of the source's most-used symbols across the fonts a")
        print("  machine might substitute (Y = has a glyph):")
        print("    %-22s %s" % ("font", " ".join("%-3s" % c for c in hot)))
        for name, fn in SUBSTITUTES:
            p = os.path.join(fd, fn)
            if not os.path.exists(p):
                print("    %-22s (not installed here)" % name)
                continue
            sub = cmaps(p)
            print("    %-22s %s" % (name, " ".join(
                "%-3s" % ("Y" if covered(sub, ord(c)) else ".") for c in hot)))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
