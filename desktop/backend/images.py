"""Isolated image documents; heavy rendering lives in a short-lived process."""

from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .project import atomic_json, digest

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 16_000_000


def finite(value, minimum, maximum, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{label} is outside the supported range.")
    return int(round(value))


def color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("Use a six-digit image color.")
    return value.lower()


def validate_document(blocks, strokes, width, height):
    if not isinstance(blocks, list) or not isinstance(strokes, list) or len(blocks) > 100 or len(strokes) > 500:
        raise ValueError("Keep this image below 100 text regions and 500 brush strokes.")
    clean, seen = [], set()
    for block in blocks:
        if not isinstance(block, dict) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(block.get("id", ""))) or block["id"] in seen:
            raise ValueError("Image region identities must be unique.")
        seen.add(block["id"])
        box = block.get("box")
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError("A text region needs x, y, width and height in image pixels.")
        x, y = finite(box[0], 0, width - 1, "Region x"), finite(box[1], 0, height - 1, "Region y")
        w, h = finite(box[2], 1, width - x, "Region width"), finite(box[3], 1, height - y, "Region height")
        source, target = block.get("source", ""), block.get("target", "")
        if not all(isinstance(text, str) and len(text.encode()) <= 8000 for text in (source, target)):
            raise ValueError("Keep each image text field below 8 KB.")
        style = block.get("style", {})
        if not isinstance(style, dict):
            raise ValueError("Invalid image text style.")
        background = style.get("background", "auto")
        align = style.get("align", "center")
        if background not in {"auto", "keep", "solid", "transparent", "vgradient", "hgradient", "patch", "inpaint"} or align not in {"left", "center", "right"}:
            raise ValueError("Unsupported image background or alignment.")
        clean.append({"id": block["id"], "box": [x, y, w, h], "source": source, "target": target,
                      "style": {"background": background, "fill": color(style.get("fill", "#20242c")),
                                "text_color": color(style.get("text_color", "#ffffff")), "align": align,
                                "cap_height": finite(style.get("cap_height", 20), 5, 400, "Text size"),
                                "bold": bool(style.get("bold", False)), "italic": bool(style.get("italic", False))}})
        item = clean[-1]
        item.update(angle=finite(block.get('angle', 0), -180, 180, 'Text rotation'), skip=bool(block.get('skip', False)))
        for key in ('lines', 'flags'):
            values = block.get(key, [])
            if not isinstance(values, list) or len(values) > 500 or len(json.dumps(values)) > 100_000:
                raise ValueError('Invalid OCR geometry or review flags.')
            item[key] = values
        target_style = item['style']
        for key, default, low, high in [('outline_width', 0, 0, 5), ('fill_alpha', 255, 0, 255), ('text_color_alpha', 255, 0, 255),
                                      ('outline_color_alpha', 255, 0, 255), ('scale_x', 100, 10, 400), ('scale_y', 100, 10, 400), ('tracking', 0, -200, 1000)]:
            target_style[key] = finite(style.get(key, default), low, high, key)
        target_style['outline_color'] = color(style.get('outline_color', '#000000'))
        for key in ('font', 'inpaint_method'):
            text = style.get(key, '')
            if not isinstance(text, str) or len(text) > 240 or '\0' in text:
                raise ValueError('Invalid image font or reconstruction method.')
            target_style[key] = text
        target_style.update(overflow=bool(style.get('overflow')), locked=bool(style.get('locked', background != 'auto')))
        for key in ('row_colors', 'column_colors'):
            rows = style.get(key, [])
            if not isinstance(rows, list) or len(rows) > max(width, height) or any(not isinstance(row, list) or len(row) != 4 for row in rows):
                raise ValueError('Invalid image gradient samples.')
            target_style[key] = [[finite(c, 0, 255, 'Gradient colour') for c in row] for row in rows]
        donor = style.get('donor')
        if donor is not None:
            if not isinstance(donor, list) or len(donor) != 4:
                raise ValueError('The donor region needs x, y, width and height.')
            dx, dy, dw, dh = donor
            target_style['donor'] = [finite(dx, 0, width - 1, 'Donor x'), finite(dy, 0, height - 1, 'Donor y'),
                                     finite(dw, 1, width - dx, 'Donor width'), finite(dh, 1, height - dy, 'Donor height')]
        confidence = style.get('confidence', 0)
        if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError('Invalid measurement confidence.')
        target_style['confidence'] = confidence
        target_style['notes'] = [str(note)[:1000] for note in style.get('notes', [])[:50]]
    clean_strokes, total_points = [], 0
    for stroke in strokes:
        if not isinstance(stroke, dict) or stroke.get("tool") not in {"paint", "erase-paint", "cut"}:
            raise ValueError("Choose paint, erase paint, or transparent erase.")
        points = stroke.get("points")
        if not isinstance(points, list) or not 1 <= len(points) <= 2000:
            raise ValueError("A brush stroke needs 1–2,000 image points.")
        total_points += len(points)
        if total_points > 20_000:
            raise ValueError("This image has too many brush points; simplify its touch-up layer.")
        values = []
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError("Invalid brush point.")
            values.append([finite(point[0], 0, width - 1, "Brush x"), finite(point[1], 0, height - 1, "Brush y")])
        clean_strokes.append({"tool": stroke["tool"], "points": values, "size": finite(stroke.get("size", 12), 1, 400, "Brush size"),
                              "color": color(stroke.get("color", "#20242c"))})
    return clean, clean_strokes


class ImageStore:
    def __init__(self, workspace):
        self.root = Path(workspace) / "images"

    def folder(self, project_id, image_id):
        if not re.fullmatch(r"[0-9a-f]{32}", project_id) or not re.fullmatch(r"[0-9a-f]{24}", image_id):
            raise ValueError("Invalid image identity.")
        folder = self.root / project_id / image_id
        if self.root.is_symlink() or folder.is_symlink() or not folder.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("The image workspace must not point outside its storage.")
        return folder

    def read(self, project_id, image_id):
        folder = self.folder(project_id, image_id)
        data = json.loads((folder / "image.json").read_text(encoding="utf-8"))
        if data.get("version") != 1 or data.get("id") != image_id or data.get("project_id") != project_id:
            raise ValueError("Unsupported or mismatched image document.")
        return data

    def list(self, project_id):
        if not re.fullmatch(r"[0-9a-f]{32}", project_id):
            raise ValueError("Invalid project identity.")
        rows = []
        for path in (self.root / project_id).glob("*/image.json"):
            data = self.read(project_id, path.parent.name)
            rows.append({key: data[key] for key in ("id", "name", "width", "height", "revision", "preview_revision", "approved_revision")})
        return sorted(rows, key=lambda row: row["name"].casefold())

    def import_image(self, project_id, name, data_url, source_path=""):
        from PIL import Image, ImageOps
        if not isinstance(name, str) or not name or name in {".", ".."} or len(name) > 240 or any(char in name for char in "/\\\0"):
            raise ValueError("Choose an image with a regular filename.")
        if not isinstance(data_url, str) or len(data_url) > MAX_IMAGE_BYTES * 4 // 3 + 100:
            raise ValueError("Choose an image below 20 MB.")
        if not re.match(r"^data:image/(png|jpeg|webp);base64,", data_url):
            raise ValueError("Choose a PNG, JPEG or WebP image.")
        raw = base64.b64decode(data_url.split(",", 1)[1], validate=True)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("Choose an image below 20 MB.")
        original_raw = raw
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
            mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(image.format)
            if not mime or width * height > MAX_PIXELS:
                raise ValueError("For responsive editing, use PNG/JPEG/WebP images up to 16 million pixels.")
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            orientation = image.getexif().get(274, 1)
        if orientation != 1:
            with Image.open(io.BytesIO(raw)) as image:
                oriented = ImageOps.exif_transpose(image)
                try:
                    width, height = oriented.size
                    buffer = io.BytesIO()
                    oriented.save(buffer, format="PNG")
                    raw = buffer.getvalue()
                finally:
                    oriented.close()
            mime = "image/png"
            if len(raw) > MAX_IMAGE_BYTES:
                raise ValueError("The orientation-corrected image exceeds 20 MB. Resize it before editing.")
        signature = digest(raw)
        identity = digest((str(source_path or name) + ":" + digest(original_raw)).encode())[:24]
        folder = self.folder(project_id, identity)
        if (folder / "image.json").is_file():
            return self.get(project_id, identity)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "source.bin").write_bytes(raw)
        if raw != original_raw:
            (folder / "imported-original.bin").write_bytes(original_raw)
        atomic_json(folder / "image.json", {"version": 1, "id": identity, "project_id": project_id, "name": name,
                    "mime": mime, "width": width, "height": height, "source_sha256": signature, "imported_sha256": digest(original_raw), "blocks": [], "strokes": [],
                    "revision": 0, "preview_revision": None, "approved_revision": None, "notes": []})
        return self.get(project_id, identity)

    def get(self, project_id, image_id, pixels=True):
        data = self.read(project_id, image_id)
        if pixels:
            folder = self.folder(project_id, image_id)
            source = (folder / "source.bin").read_bytes()
            if digest(source) != data["source_sha256"]:
                raise ValueError("The stored original changed. Import the image again.")
            data["original_url"] = f"data:{data['mime']};base64," + base64.b64encode(source).decode()
            for key, filename in (("preview_url", "preview.png"), ("base_url", "base.png"), ("overlay_url", "overlay.png"), ("paint_url", "paint.png"), ("cut_url", "cut.png")):
                path = folder / filename
                if path.is_file():
                    data[key] = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
        return data

    def save(self, project_id, image_id, revision, blocks, strokes):
        data = self.read(project_id, image_id)
        if data["revision"] != revision:
            raise ValueError("This image changed elsewhere. Reload it before saving.")
        blocks, strokes = validate_document(blocks, strokes, data["width"], data["height"])
        if data["blocks"] != blocks or data["strokes"] != strokes:
            data.update(blocks=blocks, strokes=strokes, revision=revision + 1, approved_revision=None)
            if data.get('link'):
                from .image_link import sync
                sync(data)
            atomic_json(self.folder(project_id, image_id) / "image.json", data)
        return data

    def render(self, project_id, image_id, operation_dir, stopped, commit_lock):
        data = self.read(project_id, image_id)
        folder = self.folder(project_id, image_id)
        source = folder / "source.bin"
        if data.get('link'):
            from .image_link import current
            current(data)
        if digest(source.read_bytes()) != data["source_sha256"]:
            raise ValueError("The stored original changed before rendering.")
        operation_dir.mkdir(parents=True, exist_ok=True)
        atomic_json(operation_dir / "request.json", {**data, "source_path": str(source), 'layer_folder': str(folder)})
        with (operation_dir / "renderer.log").open("w", encoding="utf-8") as log:
            env = {key: value for key, value in os.environ.items() if key in {
                "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "HOME", "USERPROFILE", "LOCALAPPDATA", "FONTCONFIG_PATH"
            }}
            env.update(PYTHON_DOTENV_DISABLED="1", DAZEDTL_TEST_OFFLINE="1", PYTHONIOENCODING="utf-8")
            process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("image_worker.py")), str(operation_dir / "request.json")],
                                       stdout=log, stderr=log, cwd=operation_dir, env=env)
            try:
                started = time.monotonic()
                while process.poll() is None:
                    if stopped():
                        raise InterruptedError("Image rendering stopped; the original and previous preview remain available.")
                    if time.monotonic() - started > 60:
                        raise ValueError("Rendering exceeded 60 seconds. Reduce the image or region complexity.")
                    time.sleep(.05)
                if process.returncode:
                    result_path = operation_dir / "result.json"
                    result = json.loads(result_path.read_text()) if result_path.exists() else {}
                    raise ValueError(result.get("error") or "The renderer failed. Check that NumPy and OpenCV are installed.")
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
        rendered = json.loads((operation_dir / "result.json").read_text(encoding="utf-8"))
        with commit_lock:
            current = self.read(project_id, image_id)
            if current["revision"] != data["revision"]:
                return {"stale": True, "message": "The image was edited during rendering. Render again to preview the latest changes."}
            if current.get('link'):
                from .image_link import current as linked_current
                linked_current(current)
            for name in ("preview.png", "base.png", "overlay.png"):
                temporary = folder / (name + ".tmp")
                shutil.copyfile(operation_dir / name, temporary)
                temporary.replace(folder / name)
            current.update(preview_revision=current["revision"], approved_revision=None, notes=rendered["notes"],
                           preview_sha256=digest((folder / "preview.png").read_bytes()))
            current['blocks'] = rendered['blocks']
            if current.get('link'):
                from .image_link import sync
                sync(current)
            atomic_json(folder / "image.json", current)
            return {"stale": False, "failures": sum(not note["ok"] for note in current["notes"]), "revision": current["revision"]}

    def approve(self, project_id, image_id, revision):
        data = self.read(project_id, image_id)
        if data["revision"] != revision or data["preview_revision"] != revision or any(not note["ok"] for note in data["notes"]):
            raise ValueError("Render the current image and resolve its rendering errors before approving it.")
        data["approved_revision"] = revision
        if data.get('link'):
            from .image_link import current, sync
            root, job, entry, paths = current(data)
            preview = self.folder(project_id, image_id) / 'preview.png'
            if digest(preview.read_bytes()) != data.get('preview_sha256'):
                raise ValueError('The preview changed after rendering. Render again before writing it.')
            if not paths['original'].is_file():
                paths['original'].parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(paths['editable'], paths['original'])
            # Refresh expected files after stashing the original, then save the
            # portable review state before publishing this approved PNG.
            from .image_link import file_hashes, files
            data['link']['files'] = file_hashes(files(root, entry['image']))
            temp = paths['editable'].with_suffix('.png.tmp')
            shutil.copyfile(preview, temp)
            temp.replace(paths['editable'])
            data['link']['files'] = file_hashes(files(root, entry['image']))
            sync(data, approved=True)
        atomic_json(self.folder(project_id, image_id) / "image.json", data)
        return data

    def review(self, project_id, image_id, revision, confirmed):
        from .image_link import current, signature
        data = self.read(project_id, image_id)
        if data['revision'] != revision or not data.get('link'):
            raise ValueError('Reload the portable image before confirming its text.')
        if confirmed and not any(b['source'].strip() and not b.get('skip') for b in data['blocks']):
            raise ValueError('Enter or read some image text before confirming it.')
        root, job, entry, paths = current(data)
        entry['status'] = 'confirmed' if confirmed else 'needs_review'
        atomic_json(root / '.dazedtl/image_job.json', job)
        data.update(status=entry['status'])
        data['link']['entry_hash'] = signature(entry)
        atomic_json(self.folder(project_id, image_id) / 'image.json', data)
        return data

    def export(self, project_id, image_id, destination):
        data = self.read(project_id, image_id)
        if data["approved_revision"] != data["revision"] or data["preview_revision"] != data["revision"]:
            raise ValueError("Approve the current preview before exporting it.")
        folder = self.folder(project_id, image_id)
        if digest((folder / "preview.png").read_bytes()) != data.get("preview_sha256"):
            raise ValueError("The preview changed after approval; render it again.")
        destination.mkdir(parents=True, exist_ok=True)
        name = Path(data["name"]).stem + ".png"
        shutil.copyfile(folder / "preview.png", destination / name)
        atomic_json(destination / "dazedtl-image.json", {"image": name, "source_sha256": data["source_sha256"], "revision": data["revision"]})
        return {"path": str(destination), "file": name}
