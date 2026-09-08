r"""What pixel size reproduces the engine's own text layer?

    calibrate_font.py --fit "a line observed to sit on ONE row"
    calibrate_font.py --fit "..." --break-after "you're a"
    calibrate_font.py                      corroboration sweep only

Bakin r64268 exposes no font-size field on a widget, so `config.font_size`
cannot be READ. It is the size at which a PIL-class measuring library
reproduces what the engine's native layer did, which makes it a calibration
constant - and a constant nobody can re-derive is one that silently rots the
first time the font changes. `config.font_size` and `measure.resolve` both
point here.

A RENDER IS THE ONLY REAL EVIDENCE. Give it observations read off a screenshot
of the running game:

    --fit TEXT           TEXT was seen occupying exactly one row.
                         => size must be small enough that TEXT fits.
    --break-after TOKEN  with --fit, the row was seen to END after TOKEN.
                         => size must also be large enough that the NEXT word
                            did not fit. This is the half that pins it down.

`--fit` alone gives an upper bound, which every smaller size also satisfies.
Only the pair brackets the answer, so the tool says which bound it has.

WHY THE SHIPPED JAPANESE IS NOT ENOUGH, MEASURED RATHER THAN ASSUMED.
The tempting shortcut is to calibrate against the author's own hard-wrapped
Japanese: their lines had to fit, and they broke where the next word did not.
The second half is false for this corpus. Over 44,056 author-placed breaks the
"the next word would still have fitted" rate is 99.97% at 16px and 90.52% at
24px - it never bottoms out, because a Japanese author breaks dialogue at
PHRASE boundaries for readability, not at the margin. The overflow side is
softer than it looks too: `MessageEntry.wordWrap` re-breaks only lines that
EXCEED the box, so an author line a little too wide is repaired at runtime and
costs them nothing. The sweep is printed as corroboration, and reading it as
proof is how a plausible wrong size gets adopted."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import ImageFont                                          # noqa: E402

from artl import config, store                                     # noqa: E402

CANDIDATES = [
    ("Yu Gothic Light", r"C:/Windows/Fonts/YuGothL.ttc"),
    ("Yu Gothic Regular", r"C:/Windows/Fonts/YuGothR.ttc"),
    ("Yu Gothic Medium", r"C:/Windows/Fonts/YuGothM.ttc"),
    ("Yu Gothic Bold", r"C:/Windows/Fonts/YuGothB.ttc"),
    ("MS Gothic", r"C:/Windows/Fonts/msgothic.ttc"),
]
SIZES = range(14, 35)


def faces(cfg):
    """Candidates, with the bundled file first.

    `GraphicsCore.createFont` probes `font.ttf` beside the executable and under
    `sysresource/`, and `setGameFont` sets `useSystemFont = !IsNullOrEmpty(name)`
    - so an EMPTY `GameSettings.gameFont` selects that file and nothing on the
    player's machine can change what they see."""
    p = os.path.join(cfg["proj_dir"], "font.ttf")
    out = [("bundled font.ttf", p)] if os.path.exists(p) else []
    return out + [(n, q) for n, q in CANDIDATES if os.path.exists(q)]


def author_breaks(cfg):
    """[(line, first_word_of_next)] over every author-wrapped Japanese body."""
    out = []
    for _p, u in store.all_units(store.load_docs(cfg["store_dir"])):
        if u["kind"] != "text":
            continue
        src = u.get("src") or ""
        if "\n" not in src:
            continue
        lines = src.split("\n")
        for i, line in enumerate(lines[:-1]):
            nxt = lines[i + 1].strip()
            if not line.strip() or not nxt:
                continue
            head = nxt[0]
            if head.isascii() and head.isalpha():
                head = nxt.split(" ")[0]
            out.append((line, head))
    return out


def main(*argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = config.load()

    def opt(name, dflt=None):
        return argv[argv.index(name) + 1] if name in argv else dflt

    width = float(opt("--width", cfg["wrap_px"]["message"]))
    fit = opt("--fit")
    brk = opt("--break-after")

    print("panel %.0fpx\n" % width)

    if fit:
        print("OBSERVED: %r sat on one row%s\n"
              % (fit[:60], (" and ended after %r" % brk) if brk else ""))
        print("  %-22s %s" % ("face", "sizes consistent with the observation"))
        for name, path in faces(cfg):
            ok = []
            for size in SIZES:
                f = ImageFont.truetype(path, size)
                if f.getlength(fit) > width:
                    continue
                if brk:
                    # The row ended after TOKEN, so the next word must NOT have
                    # fitted. Everything up to and including TOKEN, plus the
                    # word after it, has to exceed the panel.
                    i = fit.find(brk)
                    if i < 0:
                        print("  %-22s  --break-after %r is not in --fit" % (name, brk))
                        ok = None
                        break
                    head = fit[:i + len(brk)]
                    rest = fit[i + len(brk):].strip().split(" ")
                    if not rest or not rest[0]:
                        continue
                    if f.getlength(head + " " + rest[0]) <= width:
                        continue
                ok.append(size)
            if ok is None:
                continue
            if ok:
                span = "%d" % ok[0] if len(ok) == 1 else "%d-%d" % (ok[0], ok[-1])
                bound = "bracketed" if brk else "UPPER BOUND only"
                print("  %-22s %-12s (%s)" % (name, span + "px", bound))
            else:
                print("  %-22s none" % name)
        if not brk:
            print("\n  Add --break-after to bracket it; --fit alone is satisfied by\n"
                  "  every smaller size too.")
        return 0

    pairs = author_breaks(cfg)
    print("CORROBORATION ONLY - %d author-placed Japanese breaks." % len(pairs))
    print("Read the docstring before believing this: the `premature` column\n"
          "never bottoms out, so it cannot pin the size down.\n")
    print("  %-22s %-6s %10s %11s" % ("face", "size", "overflow%", "premature%"))
    for name, path in faces(cfg):
        for size in SIZES:
            if size % 2:
                continue
            f = ImageFont.truetype(path, size)
            over = early = 0
            for line, head in pairs:
                w = f.getlength(line)
                if w > width:
                    over += 1
                elif w + f.getlength(head) <= width:
                    early += 1
            print("  %-22s %-6d %9.2f %10.2f"
                  % (name if size == 14 else "", size,
                     100.0 * over / len(pairs), 100.0 * early / len(pairs)))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
