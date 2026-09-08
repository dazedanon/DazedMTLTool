from pathlib import Path
from PIL import Image, ImageFilter


def main() -> None:
    mask_dir = Path("work/prolag_masks")
    for path in sorted(mask_dir.glob("mask_*.png")):
        img = Image.open(path).convert("L")
        # Make any rendered subtitle pixels white, then expand the mask enough
        # to cover the original text outline and soft shadow.
        img = img.point(lambda p: 255 if p > 8 else 0)
        img = img.filter(ImageFilter.MaxFilter(7))
        img.save(path)


if __name__ == "__main__":
    main()
