#!/usr/bin/env python3
"""Build a review index of the game's images, ranked by how likely each is to
have Japanese text baked into it.

Nothing here reads pixels for meaning - it ranks by the evidence that is cheap
and reliable: a Japanese filename, a folder that the scripts use for UI, and the
aspect/size profile of a button or label rather than a character sprite. Open the
top of the list, tick off what really needs redrawing, and feed that list to
``Tools\\Game Translation\\Image Translation\\imgtl.py``.

    python tools/scripts/image_review.py
    python tools/scripts/image_review.py --html      # contact sheets per folder
"""
from __future__ import annotations

import argparse
import csv
import html
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
IMAGES = HERE / "extracted" / "images"
APP = HERE / "extracted" / "app"
OUT = HERE / "extracted"

JP_RE = re.compile(r"[぀-ゟ゠-ヿ一-鿿]")

#: folders whose whole purpose is interface furniture
UI_FOLDERS = {
    "data/image/base_ui", "data/image/blui", "data/image/button", "data/image/cautionui",
    "data/image/config", "data/image/hideoutui", "data/image/hsceneui", "data/image/kigaeui",
    "data/image/mesbox", "data/image/saveload", "data/image/tansakuui", "data/image/title",
    "data/image/yui", "tyrano/images/system", "tyrano/images",
}
#: folders that are artwork - a sprite or a background, text is unlikely
ART_FOLDERS = ("data/fgimage/", "data/bgimage/", "data/image/kaisou_cg",
               "data/image/cgmode", "data/image/replay_", "data/image/womb")


def size_of(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image
    except ImportError:
        return (0, 0)
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return (0, 0)


def referenced_names(app_root: Path) -> Counter:
    """How often each image file name appears in the scripts."""
    counts: Counter = Counter()
    if not app_root.exists():
        return counts
    pattern = re.compile(r'([\w \-./\\()（）぀-ヿ一-鿿]+\.(?:png|jpe?g|gif))', re.I)
    for path in app_root.rglob("*"):
        if path.suffix.lower() not in (".ks", ".js", ".html", ".css"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in pattern.findall(text):
            counts[match.replace("\\", "/").split("/")[-1].lower()] += 1
    return counts


def score(rel: str, name: str, width: int, height: int, refs: int) -> tuple[int, list[str]]:
    reasons: list[str] = []
    points = 0
    folder = rel.rsplit("/", 1)[0]

    if JP_RE.search(name):
        points += 60
        reasons.append("Japanese filename")
    if folder in UI_FOLDERS:
        points += 30
        reasons.append("UI folder")
    if rel.startswith(ART_FOLDERS):
        points -= 25
        reasons.append("artwork folder")
    if refs:
        points += 5
        reasons.append(f"referenced {refs}x")

    if width and height:
        ratio = width / max(height, 1)
        if 1.6 <= ratio <= 14 and height <= 220:
            points += 20
            reasons.append("button/label shape")
        if width >= 1200 and height >= 700:
            points -= 15
            reasons.append("full-screen art")
    return points, reasons


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--html", action="store_true", help="also write contact sheets")
    ap.add_argument("--top", type=int, default=400, help="rows in the shortlist")
    args = ap.parse_args()

    if not IMAGES.exists():
        raise SystemExit(f"{IMAGES} missing - run `tl.py unpack --images`")

    refs = referenced_names(APP)
    rows = []
    for path in sorted(IMAGES.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif"):
            continue
        rel = path.relative_to(IMAGES).as_posix()
        width, height = size_of(path)
        hits = refs.get(path.name.lower(), 0)
        points, reasons = score(rel, path.name, width, height, hits)
        rows.append({
            "score": points, "path": rel, "name": path.name,
            "w": width, "h": height, "kb": round(path.stat().st_size / 1024, 1),
            "refs": hits, "why": "; ".join(reasons),
        })

    rows.sort(key=lambda r: (-r["score"], r["path"]))

    csv_path = OUT / "image_review.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=["score", "path", "w", "h", "kb", "refs", "why"],
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    by_folder: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_folder[row["path"].rsplit("/", 1)[0]].append(row)

    lines = ["Image review - candidates for baked-in Japanese text",
             "=" * 60, "",
             f"{len(rows)} images scanned. Full ranking: {csv_path.name}", "",
             "Folders, by how many likely-text images they hold:", ""]
    ranked = sorted(by_folder.items(),
                    key=lambda kv: -sum(1 for r in kv[1] if r["score"] >= 30))
    for folder, items in ranked:
        likely = sum(1 for r in items if r["score"] >= 30)
        lines.append(f"  {likely:5d} likely / {len(items):5d} total   {folder}")
    lines += ["", "Top candidates:", ""]
    for row in rows[:args.top]:
        if row["score"] < 20:
            break
        lines.append(f"  {row['score']:4d}  {row['w']:>5}x{row['h']:<5} {row['path']}")
        lines.append(f"        {row['why']}")
    report = "\n".join(lines) + "\n"
    (OUT / "image_review.txt").write_text(report, encoding="utf-8")
    print(report[:4000])
    print(f"-> {OUT / 'image_review.txt'}")
    print(f"-> {csv_path}")

    if args.html:
        sheets = OUT / "image_sheets"
        sheets.mkdir(exist_ok=True)
        index = ["<h1>Image contact sheets</h1><ul>"]
        for folder, items in ranked:
            slug = folder.replace("/", "_")
            cards = []
            for row in items:
                src = (IMAGES / row["path"]).as_uri()
                cards.append(
                    f'<figure style="display:inline-block;margin:6px;width:190px;'
                    f'vertical-align:top;font:11px/1.3 monospace">'
                    f'<img src="{src}" style="max-width:180px;max-height:150px;'
                    f'background:#333">'
                    f'<figcaption>{html.escape(row["name"])}<br>'
                    f'{row["w"]}x{row["h"]} score {row["score"]}</figcaption></figure>')
            page = (f'<meta charset="utf-8"><title>{html.escape(folder)}</title>'
                    f'<body style="background:#111;color:#ddd">'
                    f'<h2>{html.escape(folder)}</h2>' + "".join(cards))
            (sheets / f"{slug}.html").write_text(page, encoding="utf-8")
            index.append(f'<li><a href="{slug}.html">{html.escape(folder)}</a> '
                         f'({len(items)})</li>')
        index.append("</ul>")
        (sheets / "index.html").write_text(
            '<meta charset="utf-8"><body style="background:#111;color:#ddd">'
            + "".join(index), encoding="utf-8")
        print(f"-> {sheets / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
