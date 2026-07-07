"""Extract the largest embedded icon from a Windows PE executable as PNG."""

from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image

try:
    import pefile
except ImportError:  # pragma: no cover - pefile is a dev/runtime dependency
    pefile = None  # type: ignore[assignment]


def _raw_icon_to_image(raw: bytes) -> Image.Image | None:
    """Decode a single RT_ICON blob (PNG-embedded or BMP) to RGBA."""
    png_start = raw.find(b"\x89PNG")
    if png_start >= 0:
        return Image.open(io.BytesIO(raw[png_start:])).convert("RGBA")

    if len(raw) < 40:
        return None

    bi_size = struct.unpack("<I", raw[0:4])[0]
    bi_width = struct.unpack("<i", raw[4:8])[0]
    bi_height = struct.unpack("<i", raw[8:12])[0]
    bi_bpp = struct.unpack("<H", raw[14:16])[0]
    actual_h = abs(bi_height) // 2
    if bi_width <= 0 or actual_h <= 0:
        return None

    pixel_offset = bi_size
    if bi_bpp <= 8:
        num_colors = struct.unpack("<I", raw[32:36])[0] or (2**bi_bpp)
        pixel_offset += num_colors * 4

    row_bytes = ((bi_width * bi_bpp + 31) // 32) * 4
    xor_data = raw[pixel_offset : pixel_offset + row_bytes * actual_h]

    if bi_bpp == 32:
        img = Image.frombytes("RGBA", (bi_width, actual_h), xor_data[: bi_width * actual_h * 4])
    elif bi_bpp == 24:
        img = Image.frombytes("RGB", (bi_width, actual_h), xor_data[: bi_width * actual_h * 3]).convert("RGBA")
    elif bi_bpp == 8:
        num_colors = struct.unpack("<I", raw[32:36])[0] or 256
        palette: list[int] = []
        for c in range(num_colors):
            b, g, r, _ = struct.unpack("BBBB", raw[40 + c * 4 : 44 + c * 4])
            palette.extend([r, g, b])
        img = Image.frombytes("P", (bi_width, actual_h), xor_data[: bi_width * actual_h])
        img.putpalette(palette)
        img = img.convert("RGBA")
    else:
        return None

    return img.transpose(Image.FLIP_TOP_BOTTOM)


def extract_icon_blobs(exe_path: str | Path) -> dict[int, bytes]:
    """Return ``{resource_id: raw_icon_bytes}`` from *exe_path*."""
    if pefile is None:
        raise RuntimeError("pefile is required to extract icons from executables")

    pe = pefile.PE(str(exe_path), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])

    blobs: dict[int, bytes] = {}
    if hasattr(pe, "DIRECTORY_ENTRY_RESOURCE"):
        for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            if entry.id != pefile.RESOURCE_TYPE["RT_ICON"]:
                continue
            for icon_entry in entry.directory.entries:
                icon_id = icon_entry.struct.Id
                for data_entry in icon_entry.directory.entries:
                    offset = data_entry.data.struct.OffsetToData
                    size = data_entry.data.struct.Size
                    blobs[icon_id] = pe.get_data(offset, size)
    pe.close()
    return blobs


def extract_best_icon_image(exe_path: str | Path) -> Image.Image | None:
    """Return the largest decodable icon from *exe_path*, or ``None``."""
    blobs = extract_icon_blobs(exe_path)
    if not blobs:
        return None

    best_raw = max(blobs.values(), key=len)
    return _raw_icon_to_image(best_raw)


def extract_best_icon_png(exe_path: str | Path, out_path: str | Path, *, min_size: int = 0) -> tuple[int, int] | None:
    """Write the largest icon from *exe_path* to *out_path*; return size or ``None``."""
    img = extract_best_icon_image(exe_path)
    if img is None:
        return None
    if min_size and max(img.size) < min_size:
        scale = min_size / max(img.size)
        new_w = max(1, int(round(img.width * scale)))
        new_h = max(1, int(round(img.height * scale)))
        img = img.resize((new_w, new_h), Image.Resampling.NEAREST)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return img.size
