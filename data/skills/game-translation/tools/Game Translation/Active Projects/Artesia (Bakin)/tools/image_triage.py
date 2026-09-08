"""Scope the image-translation pass without opening 3,395 files.

    image_triage.py <resources.tsv> [imgout]

`BakinTL resources` classifies every asset the catalog knows about by ROM TYPE,
and type is what separates 2D art that can carry baked-in Japanese (`Sprite`,
`Window`, `Icon`, `Face`, `NSprite`, backgrounds) from the model textures that
make up most of the corpus by size and can carry none.

This is a RANKING, not an answer - it says which files to look at first, and
nothing here proves a file does or does not contain text. Read
`references/image-translation.md` before editing any of them.
"""

import collections
import csv
import os
import sys

SEP = "\\"

# Path fragments that mark art a UI can draw text on. Deliberately generous:
# a false positive costs one glance, a false negative ships Japanese on screen.
UI_HINTS = ("window", "icon", "title", "logo", "menu", "system", "button",
            "plate", "frame", "cursor", "gauge", "bar", "face", "cutin",
            "message", "tutorial", "help", "status", "map_bg", "effect")

# Suffixes of a PBR channel map. These are never text.
MODEL_MAP = ("_albedo", "_normal", "_metallic", "_roughness", "_mask",
             "_emissive", "_occlusion", "_height", "_ao", "_orm",
             "basecolor", "_spec", "_gloss")


def main(res_path, imgout=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = list(csv.DictReader(open(res_path, encoding="utf-8"), delimiter="\t"))
    by_type = collections.Counter(r["type"] for r in rows)
    print("assets by rom type")
    for t, n in by_type.most_common():
        print("   %-22s %6d" % (t, n))

    # `NSprite` and `NSpriteSet` are the 2D animation layer and reference a
    # texture BY GUID - their own `path` is the bare `.\` prefix and carries no
    # file at all. Including them puts 581 pathless rows at the top of the
    # "look at these first" list, which is exactly the wrong place.
    art_types = {"Texture", "Sprite", "Window", "Icon", "Face",
                 "MapBackground", "BattleBackground", "Decal"}
    IMG = (".png", ".bmp", ".jpg", ".jpeg", ".tga", ".dds")
    art = [r for r in rows
           if r["type"] in art_types
           and (r.get("path") or "").lower().endswith(IMG)]

    ui, model, other = [], [], []
    for r in art:
        p = r["path"].lower().replace("/", SEP)
        if any(m in p for m in MODEL_MAP):
            model.append(r)
        elif any(h in p for h in UI_HINTS) or r["type"] != "Texture":
            ui.append(r)
        else:
            other.append(r)

    print()
    print("2D art rows with a path      : %d" % len(art))
    print("   look at these FIRST       : %d  (UI-shaped path, or a 2D rom type)"
          % len(ui))
    print("   PBR channel maps, skip    : %d" % len(model))
    print("   unclassified, look after  : %d" % len(other))

    if imgout:
        missing = [r for r in ui
                   if not os.path.exists(os.path.join(
                       imgout, r["path"].lstrip(".").lstrip(SEP).lstrip("/")))]
        print("   of the first group, not present in %s: %d"
              % (imgout, len(missing)))

    print()
    print("first 30 to look at:")
    for r in sorted(ui, key=lambda x: x["path"])[:30]:
        print("   %-10s %-26s %s" % (r["type"], (r["name"] or "")[:26],
                                     r["path"][:64]))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
