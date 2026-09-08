"""Same-row overlap and map-edge overflow for every `<LB:>` caption.

EventLabel centres the caption on its event (`Sprite.anchor.x = 0.5`), so the
budget that matters is the gap to the NEXT LABEL ON THE SAME ROW - labels on
different rows never touch. `<LB_X:n>` shifts a caption, so it has to be part
of the geometry, not ignored.
"""
import glob, json, os, re, sys, unicodedata

TILE = 48
LB = re.compile(r"<LB:([^>]*)>")
LBX = re.compile(r"<LB_X:(-?\d+)>")


def cells(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def spans(path, size):
    d = json.load(open(path, encoding="utf-8"))
    map_w = (d.get("width") or 0) * TILE
    out = []
    for ev in d.get("events") or []:
        if not ev:
            continue
        note = ev.get("note") or ""
        m = LB.search(note)
        if not m or not m.group(1).strip():
            continue
        mx = LBX.search(note)
        centre = ev.get("x", 0) * TILE + TILE // 2 + (int(mx.group(1)) if mx else 0)
        w = cells(m.group(1)) * (size / 2.0)
        out.append((ev.get("y", 0), centre - w / 2, centre + w / 2,
                    m.group(1), ev.get("id")))
    return map_w, out


def main(size):
    over = coll = 0
    for p in sorted(glob.glob(os.path.join(sys.argv[2], "Map[0-9]*.json"))):
        name = os.path.basename(p)
        map_w, rows = spans(p, size)
        if not map_w:
            continue
        for y, l, r, t, i in rows:
            if l < 0 or r > map_w:
                over += 1
                print("  OFFMAP  %-14s ev%-4s %-32s [%.0f,%.0f] map_w=%d"
                      % (name, i, t[:32], l, r, map_w))
        by_row = {}
        for y, l, r, t, i in rows:
            by_row.setdefault(y, []).append((l, r, t, i))
        for y, items in sorted(by_row.items()):
            items.sort()
            for (l1, r1, t1, i1), (l2, r2, t2, i2) in zip(items, items[1:]):
                if r1 > l2:
                    coll += 1
                    print("  OVERLAP %-14s y=%-3d %-26s / %-26s by %.0fpx"
                          % (name, y, t1[:26], t2[:26], r1 - l2))
    print("fontSize %d -> %d off-map, %d same-row overlap(s)" % (size, over, coll))


main(int(sys.argv[1]))
