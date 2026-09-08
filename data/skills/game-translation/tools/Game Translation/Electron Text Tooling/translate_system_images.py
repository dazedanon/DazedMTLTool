#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

from PIL import Image, ImageDraw, ImageFilter, ImageFont


TOOLING_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = TOOLING_ROOT / "unpacked_app"
SYSTEM_DIR = APP_ROOT / "tyrano" / "images" / "system"
BACKUP_ROOT = TOOLING_ROOT / "backups"

FONT_ARIAL_BOLD = Path("C:/Windows/Fonts/arialbd.ttf")
FONT_COMIC = Path("C:/Windows/Fonts/comic.ttf")
FONT_COMIC_BOLD = Path("C:/Windows/Fonts/comicbd.ttf")
FONT_HAND = Path("C:/Windows/Fonts/Inkfree.ttf")


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def text_size(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.multiline_textbbox((0, 0), text, font=fnt, spacing=0)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    path: Path,
    max_width: int,
    max_height: int,
    start: int,
    min_size: int = 8,
) -> ImageFont.ImageFont:
    for size in range(start, min_size - 1, -1):
        fnt = font(path, size)
        width, height = text_size(draw, text, fnt)
        if width <= max_width and height <= max_height:
            return fnt
    return font(path, min_size)


def backup_system_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = BACKUP_ROOT / f"system_original_{stamp}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SYSTEM_DIR, destination)
    return destination


def clear_rgba(image: Image.Image, box: tuple[int, int, int, int]) -> None:
    image.paste(Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), (0, 0, 0, 0)), box)


def draw_centered(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    fnt: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    stroke_fill: tuple[int, int, int, int],
    stroke_width: int,
    spacing: int = 0,
) -> None:
    width, height = text_size(draw, text, fnt)
    x = box[0] + ((box[2] - box[0]) - width) / 2
    y = box[1] + ((box[3] - box[1]) - height) / 2
    draw.multiline_text(
        (x, y),
        text,
        font=fnt,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
        spacing=spacing,
        align="center",
    )


def translate_label(filename: str, text: str) -> None:
    path = SYSTEM_DIR / filename
    image = Image.open(path).convert("RGBA")
    draw = ImageDraw.Draw(image)
    clear_rgba(image, (17, 105, 150, 138))
    fnt = fit_font(draw, text, FONT_ARIAL_BOLD, 124, 24, 20)
    draw.text(
        (20, 108),
        text,
        font=fnt,
        fill=(28, 28, 28, 255),
        stroke_width=1,
        stroke_fill=(255, 255, 255, 230),
    )
    image.save(path)


def translate_menu_button(filename: str, text: str, box: tuple[int, int, int, int], size: int) -> None:
    path = SYSTEM_DIR / filename
    image = Image.open(path).convert("RGBA")
    blurred = image.filter(ImageFilter.GaussianBlur(7))
    image.paste(blurred.crop(box), box)
    wash = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), (255, 255, 255, 44))
    image.alpha_composite(wash, (box[0], box[1]))
    draw = ImageDraw.Draw(image)
    fnt = fit_font(draw, text, FONT_ARIAL_BOLD, box[2] - box[0] - 8, box[3] - box[1] - 6, size)
    draw_centered(
        draw,
        box,
        text,
        fnt,
        fill=(255, 255, 255, 255),
        stroke_fill=(20, 20, 20, 255),
        stroke_width=3,
        spacing=0,
    )
    image.save(path)


def draw_staff_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    size: int,
    max_width: int,
    fill: tuple[int, int, int] = (34, 28, 24),
) -> None:
    fnt = fit_font(draw, text, FONT_HAND if FONT_HAND.exists() else FONT_COMIC, max_width, 44, size, 16)
    draw.text(xy, text, font=fnt, fill=fill)


def translate_staff_page() -> None:
    path = SYSTEM_DIR / "bg_staff.jpg"
    image = Image.open(path).convert("RGB")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    paper = (244, 237, 214, 255)
    line = (174, 160, 140, 115)
    draw.rectangle((145, 170, 1518, 868), fill=paper)
    for y in range(225, 860, 55):
        draw.line((180, y, 1490, y), fill=line, width=2)
    draw.rectangle((145, 170, 1518, 868), outline=(110, 95, 82, 180), width=2)
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(image)

    header = font(FONT_COMIC_BOLD, 30)
    body = font(FONT_COMIC, 28)
    small = font(FONT_COMIC, 23)

    title = "Girl Interspecies Prison"
    title_font = fit_font(draw, title, FONT_COMIC_BOLD, 330, 40, 29, 20)
    draw.text((1085, 190), title, font=title_font, fill=(35, 29, 25))
    draw.text((250, 298), "Planning ... Hasue Yuu", font=font(FONT_HAND, 40), fill=(30, 25, 22))

    draw.text((315, 390), "Materials", font=header, fill=(30, 25, 22))
    material_lines = [
        "Music ... SOUND AIRYLUVS",
        "         ruha (Pastel Tone Music)",
        "Sound Effects ... Otologic (CC BY 4.0)",
        "                 DLSite Creator Academy",
        "Some Background CG ... Minikle",
        "Some Monster CG ... Fuwafuwa Nyanko",
    ]
    y = 455
    for line_text in material_lines:
        draw.text((190, y), line_text, font=small, fill=(34, 28, 24))
        y += 42

    draw.text((1015, 255), "Voice", font=header, fill=(30, 25, 22))
    draw.text((860, 310), "Maika CV ... Momoka Sakura", font=body, fill=(34, 28, 24))
    draw.text((860, 365), "Platina CV ... Momoka Sakura", font=body, fill=(34, 28, 24))

    draw.text((1010, 420), "Creation", font=header, fill=(30, 25, 22))
    creation_lines = [
        "Character Design ... Hasue Yuu / Otogi-do",
        "Line Art / Coloring / CG ... Hasue Yuu / Otogi-do",
        "Animation ... Hasue Yuu / Otogi-do",
        "Text / Scenario ... Hasue Yuu / Otogi-do",
        "Programming / Script ... Hasue Yuu / Otogi-do",
        "UI Design ... Hasue Yuu / Otogi-do",
    ]
    y = 470
    for line_text in creation_lines:
        draw_staff_text(draw, (720, y), line_text, 29, 740)
        y += 50

    draw.text((165, 730), "Special Thanks", font=header, fill=(30, 25, 22))
    draw.text((165, 775), "In Memory of the Little Queen of Cats.", font=small, fill=(34, 28, 24))
    draw.text((165, 805), "Special Thanks to Everyone Who Purchased the Game.", font=small, fill=(34, 28, 24))

    image.save(path, quality=95, subsampling=0)


def main() -> int:
    backup = backup_system_dir()
    print(f"backup: {backup}")

    translate_label("label_backlog.png", "History")
    translate_label("label_config.png", "Settings")
    translate_label("label_load.png", "Load")
    translate_label("label_save.png", "Save")

    for filename in ("menu_button_close.png", "menu_button_close2.png"):
        translate_menu_button(filename, "BACK", (10, 29, 90, 73), 26)
    for filename in ("menu_button_titleback.png", "menu_button_titleback2.png"):
        translate_menu_button(filename, "TO\nTITLE", (4, 20, 96, 76), 24)

    translate_staff_page()
    print("translated: label_backlog.png, label_config.png, label_load.png, label_save.png")
    print("translated: menu_button_close*.png, menu_button_titleback*.png")
    print("translated: bg_staff.jpg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
