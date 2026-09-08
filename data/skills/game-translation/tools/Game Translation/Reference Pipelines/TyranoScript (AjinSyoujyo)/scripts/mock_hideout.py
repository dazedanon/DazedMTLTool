"""Composite the room-expansion screen from the script, to check the fit.

Draws the icon buttons, the ho.png plates and the ptext labels at the exact
coordinates the script gives, on a 1920x1080 canvas - the same thing the engine
does, so an overflow here is an overflow there.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, "tools/scripts")
sys.path.insert(0, "tools/scripts/imgwork")
from PIL import Image, ImageDraw  # noqa: E402
from tyranotl import codes  # noqa: E402
import imgtl  # noqa: E402

APP = Path("tools/extracted/app")
IMAGES = Path("tools/extracted/images/data")
SCRIPT = Path(sys.argv[1])
OUT = Path(sys.argv[2])
LITERAL = re.compile(r"'((?:[^'\\]|\\.)*)'")


def attr(tag, name):
    m = re.search(rf'\b{name}="([^"]*)"', tag)
    return m.group(1) if m else None


def visible(tag):
    raw = attr(tag, "text") or ""
    if not raw.startswith("&"):
        return codes.unprotect_spaces(raw)
    out, pos = [], 0
    for m in LITERAL.finditer(raw):
        if "f." in raw[pos:m.start()] or "tf." in raw[pos:m.start()]:
            out.append("0")
        out.append(m.group(1))
        pos = m.end()
    if "f." in raw[pos:] or "tf." in raw[pos:]:
        out.append("0")
    return codes.unprotect_spaces("".join(out))


canvas = Image.new("RGB", (1920, 1080), (52, 58, 64))
draw = ImageDraw.Draw(canvas)
text = SCRIPT.read_text(encoding="utf-8")
font_path = APP / "data" / "others" / "MyFont1.otf"

for m in codes.TAG_RE.finditer(text):
    tag, name = m.group(), m.group(1)
    if name == "button" and attr(tag, "graphic"):
        path = IMAGES / "image" / attr(tag, "graphic")
        if path.exists():
            icon = Image.open(path).convert("RGBA")
            canvas.paste(icon, (int(attr(tag, "x") or 0), int(attr(tag, "y") or 0)), icon)
    elif name == "image" and attr(tag, "storage") == "ho.png":
        plate = Image.open(IMAGES / "fgimage" / "ho.png").convert("RGBA")
        w, h = int(attr(tag, "width")), int(attr(tag, "height"))
        plate = plate.resize((w, h))
        canvas.paste(plate, (int(attr(tag, "x")), int(attr(tag, "y"))), plate)

# labels last, so they sit on top of their plates like the engine draws them
for m in codes.TAG_RE.finditer(text):
    tag = m.group()
    if m.group(1) != "ptext":
        continue
    x, y = int(attr(tag, "x") or 0), int(attr(tag, "y") or 0)
    size = int(attr(tag, "size") or 25)
    from PIL import ImageFont
    font = ImageFont.truetype(str(font_path), size)
    draw.text((x, y), visible(tag), font=font, fill=(255, 255, 255))
    right = x + draw.textlength(visible(tag), font=font)
    if right > 1920:
        draw.rectangle([x, y, 1919, y + size + 6], outline=(255, 60, 60), width=3)

draw.line([(1919, 0), (1919, 1079)], fill=(255, 60, 60), width=3)
canvas.save(OUT)
print("wrote", OUT)
