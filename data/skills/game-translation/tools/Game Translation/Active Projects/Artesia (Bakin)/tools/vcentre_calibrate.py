r"""Measure, off a real screenshot, how far a label's ink sits from its plate.

    vcentre_calibrate.py <screenshot.png> [--x0 300] [--x1 420] [--pitch 45]
                         [--buttons 7]

WHY THIS EXISTS. `TextDrawer.DrawString` centres `MeasureString(text).Y` - the
engine's NATIVE line height - inside the widget's box. That line height is much
taller than the visible ink and is not symmetric about it, so a label whose line
box is perfectly centred still reads as sitting high.

The size of that error cannot be computed from the font's own tables. For Yu
Gothic Light at the size this game draws:

    hhea      predicts  -0.9 px
    OS/2 win  predicts  -0.6 px
    OS/2 typo predicts  +0.1 px
    MEASURED            -5.32 px

None of them is close. `Font.measureString` is native (kmyCore) and does
something none of those describe, so the only honest source is the screen.

HOW IT WORKS. Screenshot the running game with the menu open, then for a
vertical band across the buttons:

  * rows where nearly every pixel is bright are the plate's FRAME LINES;
  * sparse bright rows between two frame lines are TEXT INK.

The offset between the two centres, divided by the scale (recovered from the
known design pitch of the buttons), is the constant. Use labels WITHOUT
descenders - `Item`, `Skill`, `Save` - because their ink box is exactly the cap
band; a `g` or `q` drags the ink centre down and biases the reading.

Feed the result to `config.layout_ink_offset_ratio` as a fraction of the drawn
font size, since every term in it scales linearly with size.
"""

import os
import sys


def rowinfo(px, y, x0, x1, thr=100):
    return sum(1 for x in range(x0, x1) if px[x, y] > thr)


def main(*argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not argv:
        print(__doc__)
        return 2
    path = argv[0]
    x0 = int(argv[argv.index("--x0") + 1]) if "--x0" in argv else 300
    x1 = int(argv[argv.index("--x1") + 1]) if "--x1" in argv else 420
    pitch = float(argv[argv.index("--pitch") + 1]) if "--pitch" in argv else 45.0

    from PIL import Image
    im = Image.open(path).convert("L")
    W, H = im.size
    px = im.load()
    band = x1 - x0

    frame = [y for y in range(H) if rowinfo(px, y, x0, x1) >= band * 0.9]
    groups = []
    for y in frame:
        if groups and y - groups[-1][-1] <= 3:
            groups[-1].append(y)
        else:
            groups.append([y])
    lines = [sum(g) / float(len(g)) for g in groups]
    if len(lines) < 4:
        print("found %d frame lines in x %d..%d - point --x0/--x1 at a band that "
              "crosses the buttons" % (len(lines), x0, x1))
        return 1

    print("screenshot %dx%d, band x %d..%d" % (W, H, x0, x1))
    print("frame lines at y: %s" % [round(v) for v in lines[:20]])

    # Consecutive pairs are a plate's top and bottom - but the band may also
    # cross a heading rule above the first button, which shifts the pairing by
    # one and silently pairs each plate's BOTTOM with the next plate's TOP.
    # Try both phases and keep the one whose plate heights actually agree.
    def pair(off):
        return [(lines[i], lines[i + 1])
                for i in range(off, len(lines) - 1, 2)]

    def spread(ps):
        hs = [b - a for a, b in ps]
        return (max(hs) - min(hs)) if hs else 1e9

    # Restrict to the BUTTON RUN. A menu column usually has other full-width
    # rules under it - section dividers, stat underlines - and letting those
    # into the pairing wrecks both phases. `--buttons` says how many plates to
    # read; the run is taken from the phase whose first N heights agree best.
    n_btn = int(argv[argv.index("--buttons") + 1]) if "--buttons" in argv else 7
    cands = [pair(0)[:n_btn], pair(1)[:n_btn]]
    cands = [c for c in cands if len(c) >= 3]
    if not cands:
        print("fewer than 3 plates found - widen the band or lower --buttons")
        return 1
    plates = min(cands, key=spread)
    other = cands[1 - cands.index(plates)] if len(cands) > 1 else []
    print("  pairing phase %d chosen over %d plates (height spread %.1f%s)"
          % (cands.index(plates), len(plates), spread(plates),
             ", other phase %.1f" % spread(other) if other else ""))
    tops = [p[0] for p in plates]
    steps = [b - a for a, b in zip(tops, tops[1:])]
    steps = [s for s in steps if s > 0]
    if not steps:
        print("could not recover the button pitch")
        return 1
    cap_pitch = sum(steps) / float(len(steps))
    scale = cap_pitch / pitch

    print("\n  button pitch %.1f px against a design pitch of %.0f -> scale %.3f"
          % (cap_pitch, pitch, scale))
    print("\n  %-6s %8s %8s %8s %9s %9s" %
          ("plate", "top", "bottom", "centre", "ink_c", "offset"))
    offs = []
    for k, (top, bot) in enumerate(plates):
        ink = [y for y in range(int(top) + 3, int(bot) - 2)
               if rowinfo(px, y, x0, x1) >= 2]
        if not ink:
            continue
        pc = (top + bot) / 2.0
        ic = (ink[0] + ink[-1]) / 2.0
        offs.append(ic - pc)
        print("  %-6d %8.0f %8.0f %8.1f %9.1f %+9.1f" % (k, top, bot, pc, ic, ic - pc))

    if not offs:
        print("no ink found between the frame lines")
        return 1
    # The MINIMUM magnitude is the cleanest reading: a label with a descender
    # drags its ink centre down and understates the offset, so take the modal
    # cluster rather than a plain mean.
    offs_sorted = sorted(offs)
    med = offs_sorted[len(offs_sorted) // 2]
    design = med / scale
    print("\n  median offset %+.1f capture px  =  %+.2f design px" % (med, design))
    print("  labels WITH descenders read smaller - discount them by eye.")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
