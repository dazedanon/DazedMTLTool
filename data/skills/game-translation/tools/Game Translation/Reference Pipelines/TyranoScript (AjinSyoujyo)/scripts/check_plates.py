"""Every [ptext] that has a plate image behind it, measured JP against EN."""
import re
import sys
from pathlib import Path

sys.path.insert(0, "tools/scripts")
from tyranotl import codes, layout  # noqa: E402

APP = Path("tools/extracted/app/data/scenario")
OUT = Path("tools/translated/data/scenario")
SCREEN = 1920
def tags(text, name):
    # codes.TAG_RE is quote-aware; [^\]]* would stop at the ] inside f.hide[3]
    return [m for m in codes.TAG_RE.finditer(text) if m.group(1) == name]
LITERAL = re.compile(r"'((?:[^'\\]|\\.)*)'")


def attr(tag, name, cast=str):
    m = re.search(rf'\b{name}="([^"]*)"', tag)
    return cast(m.group(1)) if m else None


def visible(tag):
    """The literal text of a ptext, with a digit where a variable goes."""
    raw = attr(tag, "text") or ""
    if not raw.startswith("&"):
        return raw.replace(" ", " ")
    out, pos = [], 0
    for m in LITERAL.finditer(raw):
        if "f." in raw[pos:m.start()] or "tf." in raw[pos:m.start()]:
            out.append("0")
        out.append(m.group(1))
        pos = m.end()
    if "f." in raw[pos:] or "tf." in raw[pos:]:
        out.append("0")
    return "".join(out).replace(" ", " ")


for rel in sorted(p.relative_to(OUT).as_posix() for p in OUT.rglob("*.ks")):
    en_path, jp_path = OUT / rel, APP / rel
    if not jp_path.exists():
        continue
    en = en_path.read_text(encoding="utf-8")
    jp = jp_path.read_text(encoding="utf-8")
    if "ho.png" not in en:
        continue
    # plate widths, keyed by the (x, y) they are drawn at
    plates = {}
    for tag in tags(en, 'image'):
        if 'storage="ho.png"' not in tag.group():
            continue
        plates[(attr(tag.group(), "x"), attr(tag.group(), "y"))] = (
            attr(tag.group(), "width", int), tag.start())
    print(f"== {rel}")
    for tag in tags(en, 'ptext'):
        t = tag.group()
        key = (attr(t, "x"), attr(t, "y"))
        if key not in plates:
            continue
        size = attr(t, "size", int) or 25
        text = visible(t)
        width = layout.measure(text, size, Path("tools/extracted/app"))
        plate = plates[key][0]
        x = int(key[0])
        flags = []
        if width > plate:
            flags.append(f"text {width:.0f} > plate {plate}")
        if x + max(width, plate) > SCREEN:
            flags.append(f"ends {x + max(width, plate):.0f} > screen")
        if flags:
            print(f"   x={x:<5} y={key[1]:<5} {text!r:34} {'; '.join(flags)}")
