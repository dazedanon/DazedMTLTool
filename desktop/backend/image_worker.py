"""Render a desktop image document with the existing image toolkit, offline."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"


def rgba(value):
    return [int(value[index:index + 2], 16) for index in (1, 3, 5)] + [255]


def main():
    request = Path(sys.argv[1])
    data = json.loads(request.read_text(encoding="utf-8"))
    folder = request.parent
    try:
        import socket
        def no_network(*_args, **_kwargs):
            raise RuntimeError("The image renderer is offline and cannot make network requests.")
        socket.create_connection = socket.socket.connect = socket.socket.connect_ex = no_network
        import cv2
        import numpy as np
        from PIL import Image
        from util.imagetools import render, paint
        from util.imagetools.geometry import Box
        from util.imagetools.job import ImageEntry, TextBlock
        from util.imagetools.style import Style
        cv2.setNumThreads(1)
        source = render.load_rgba(data["source_path"])
        if source is None:
            raise ValueError("The image could not be decoded.")
        entry = ImageEntry("preview.png", width=data["width"], height=data["height"])
        from desktop.backend.image_document import portable_block, desktop_block
        from util.imagetools.ocr import Word
        entry.blocks = [TextBlock.from_dict(portable_block(item)) for item in data['blocks']]
        entry.words = [Word.from_dict(item) for item in data.get('words', [])]
        from util.imagetools.style import adopt_background
        for block in entry.blocks:
            style = block.style
            if style is not None and (style.background == 'vgradient' and not style.row_colors or
                                      style.background == 'hgradient' and not style.column_colors or
                                      style.background == 'patch' and style.donor is None):
                message = adopt_background(source, style, block.box, [b.box for b in entry.blocks if b is not block], style.background)
                if message:
                    style.notes.append(message)
        result = render.render_entry(source, entry)
        layers = Path(data['layer_folder'])
        layer = paint._read(layers / 'paint.png', source.shape)
        cut = paint._read(layers / 'cut.png', source.shape)
        paint.apply_strokes(layer, data['strokes'])
        paint.apply_strokes(cut, data['strokes'], cut=True)
        base = result.base.copy()
        paint.apply_cut(base, cut)
        paint.composite(base, layer)
        final = np.array(Image.alpha_composite(Image.fromarray(base), Image.fromarray(result.overlay)), dtype=np.uint8)
        render.save_rgba(final, folder / "preview.png")
        render.save_rgba(result.base, folder / "base.png")
        render.save_rgba(result.overlay, folder / "overlay.png")
        notes = [{"block_id": note.block_id, "ok": note.ok, "message": note.message, "tight": note.tight} for note in result.notes]
        (folder / "result.json").write_text(json.dumps({"notes": notes, "blocks": [desktop_block(block.to_dict()) for block in entry.blocks]}, ensure_ascii=False), encoding="utf-8")
        return 0
    except Exception as exc:
        (folder / "result.json").write_text(json.dumps({"error": f"{type(exc).__name__}: {exc}"}), encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
