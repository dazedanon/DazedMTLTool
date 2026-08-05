"""The translation hand-off file.

The workflow splits at a file so the part that needs language ability runs
inside DazedTL, with the same provider, prompt and glossary as every other kind
of file the project translates:

  1. Lens reads the images; the user confirms boxes and text in the editor
  2. ``export`` writes ``image_text.json`` for the **Image Text** module
  3. ``import`` reads the translations back for rendering

Only images the user marked ``confirmed`` are exported. Nothing reaches the
translator that a human has not looked at - that gate is the point of the
whole semi-manual design.

The format is flat and boring - one object per block, source and target side by
side - so it can be edited by hand, diffed, or fed to another translator
entirely without this toolkit being involved.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from util.imagetools.fonts import text_budget
from util.imagetools.geometry import Box
from util.imagetools.job import Job, JobError

EXCHANGE_FILENAME = "image_text.json"
FORMAT_VERSION = 3


@dataclass
class ImportResult:
    applied: int = 0
    images: int = 0
    missing: list[str] = field(default_factory=list)   # in the job, absent from the file
    unknown: list[str] = field(default_factory=list)   # in the file, gone from the job
    empty: list[str] = field(default_factory=list)     # translation left blank
    source: Path | None = None


def _same_text(source: str, target: str) -> bool:
    """True when a translation left the string effectively unchanged."""
    def key(text: str) -> str:
        return "".join(ch for ch in text.lower() if ch.isalnum())

    a, b = key(source), key(target)
    return bool(a) and a == b


def exchange_path(job: Job) -> Path:
    return job.work / EXCHANGE_FILENAME


def files_path() -> Path | None:
    """Where DazedTL's Translation tab looks for input files.

    The export is mirrored here so the user translates it exactly like any
    other file: pick the **Image Text** module, press Translate, watch the log.

    ``IMGTL_FILES_DIR`` overrides the location, and an empty value disables
    mirroring. The tests set it, because an export run against a temporary
    fixture would otherwise overwrite whatever real export the user is part-way
    through translating - which is exactly what happened once. Anything that
    writes into a shared folder needs a way to be pointed somewhere else.
    """
    override = os.getenv("IMGTL_FILES_DIR")
    if override is not None:
        override = override.strip()
        if not override:
            return None
        return Path(override) / EXCHANGE_FILENAME
    try:
        from util.paths import PROJECT_ROOT
    except Exception:
        return None
    return Path(PROJECT_ROOT) / "files" / EXCHANGE_FILENAME


def build(job: Job) -> dict:
    """Everything a translator needs, and nothing it does not."""
    images = []
    for entry in job.confirmed():
        blocks = []
        for block in entry.translatable():
            orientation = "vertical" if block.vertical else "horizontal"
            blocks.append(
                {
                    "id": block.block_id,
                    "source": block.source_text,
                    "target": block.target_text,
                    # Context the translator cannot see but the layout demands.
                    "max_chars": text_budget(
                        width=block.box.w,
                        height=block.box.h,
                        cap_height=_cap_height(block),
                        orientation=orientation,
                    ),
                    "lines": block.line_count,
                    "box": block.box.as_xywh(),
                    "orientation": orientation,
                }
            )
        if blocks:
            images.append(
                {"image": entry.relpath, "index": entry.index, "regions": blocks}
            )

    return {
        "format": "dazedtl-image-text",
        "version": FORMAT_VERSION,
        "language": job.language,
        "root": str(job.root),
        "note": (
            "Fill in every 'target'. Keep it at or under 'max_chars' characters "
            "or it will not fit the image. Leave 'source' unchanged."
        ),
        "images": images,
    }


def _cap_height(block) -> int:
    """Type size, from the measured line boxes rather than the block's."""
    if block.lines:
        sizes = sorted(
            (line.box.w if block.vertical else line.box.h) for line in block.lines
        )
        return max(7, sizes[len(sizes) // 2])
    span = block.box.w if block.vertical else block.box.h
    return max(7, span // max(1, block.line_count))


def write(job: Job, path: Path | None = None) -> tuple[Path, Path | None]:
    """Write the exchange file. Returns ``(workspace copy, files/ copy)``."""
    target = Path(path) if path else exchange_path(job)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(build(job), ensure_ascii=False, indent=2)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(target)

    mirror = None
    if path is None:
        candidate = files_path()
        if candidate is not None:
            try:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text(payload, encoding="utf-8")
                mirror = candidate
            except OSError:
                mirror = None
    return target, mirror


def _belongs_to(path: Path, job: Job) -> bool:
    """Whether an exchange file was exported from *this* job.

    ``files/`` holds one image_text.json at a time, so a second game - or a
    stale file from last week - would otherwise be imported into the wrong job
    and silently overwrite its translations. The ``root`` recorded at export
    time settles it.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    recorded = str(data.get("root") or "")
    if not recorded:
        return False
    try:
        return Path(recorded).resolve() == Path(job.root).resolve()
    except OSError:
        return recorded == str(job.root)


def _translated_count(path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    return sum(
        1
        for image in data.get("images") or []
        if isinstance(image, dict)
        for region in image.get("regions") or []
        if isinstance(region, dict) and str(region.get("target") or "").strip()
    )


def _newest_source(job: Job, path: Path | None) -> Path:
    """Prefer whichever copy of *this job's* export actually has translations.

    There are two: the workspace copy written by export, and the ``files/``
    mirror the Translation tab writes back to. Timestamp alone is a bad
    tie-break - the export writes both, so a stray touch on the untranslated
    copy makes it "newest" and import silently reports twelve blank strings
    while the translations sit in the other file. Count first, then fall back to
    the timestamp when both have work in them. Only files exported from *this*
    job are considered either way.
    """
    if path is not None:
        return Path(path)
    workspace = exchange_path(job)
    mirror = files_path()
    if mirror is None or not mirror.is_file() or not _belongs_to(mirror, job):
        return workspace
    if not workspace.is_file():
        return mirror
    scores = {
        candidate: (_translated_count(candidate), candidate.stat().st_mtime)
        for candidate in (mirror, workspace)
    }
    # Ties go to the mirror: that is the one the translator just wrote.
    return max((workspace, mirror), key=lambda candidate: scores[candidate])


def _load(path: Path) -> dict:
    if not path.is_file():
        raise JobError(
            f"No translation file at {path}.\n"
            "Confirm some images and export first, then translate it in DazedTL."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise JobError(
            f"{path} is not valid JSON ({exc}).\n"
            "Re-export and translate it again without changing the file's structure."
        ) from exc
    if not isinstance(data, dict) or "images" not in data:
        raise JobError(
            f"{path} is not a DazedTL image translation file "
            "(expected an object with an 'images' list)."
        )
    return data


def read(job: Job, path: Path | None = None) -> ImportResult:
    """Copy translations from the exchange file into the job.

    Only ``target`` is read back. Boxes, source text and status stay under the
    toolkit's control, so a translator editing the file - or a model rewriting
    more of it than it was asked to - cannot corrupt the geometry.
    """
    source = _newest_source(job, path)
    data = _load(source)
    result = ImportResult(source=source)

    seen: set[tuple[str, str]] = set()
    for item in data.get("images") or []:
        if not isinstance(item, dict):
            continue
        relpath = str(item.get("image") or "")
        try:
            entry = job.find(relpath)
        except JobError:
            result.unknown.append(relpath)
            continue
        touched = False
        for record in item.get("regions") or []:
            if not isinstance(record, dict):
                continue
            block_id = str(record.get("id") or "")
            try:
                block = entry.block(block_id)
            except JobError:
                result.unknown.append(f"{relpath}:{block_id}")
                continue
            seen.add((relpath, block_id))
            target = str(record.get("target") or "").strip()
            if not target:
                result.empty.append(f"{relpath}:{block_id}")
                continue
            block.target_text = target
            # A translation identical to the source - a bare number, a string
            # already in the target language - means there is nothing to
            # redraw. Leaving the original pixels alone looks better than
            # erasing and re-rendering the same string in a different face.
            block.skip = _same_text(block.source_text, target)
            result.applied += 1
            touched = True
        if touched:
            from util.imagetools.job import TRANSLATED

            if entry.status != TRANSLATED:
                entry.status = TRANSLATED
            result.images += 1

    for entry in job.confirmed():
        for block in entry.translatable():
            if (entry.relpath, block.block_id) not in seen:
                result.missing.append(f"{entry.relpath}:{block.block_id}")
    return result


def rebuild(job: Job, path: Path | None = None) -> tuple[int, int]:
    """Recreate images and blocks the job has lost, from its exchange file.

    Returns ``(images, blocks)`` restored. The exchange holds the box, the
    corrected source text and the translation for every block that was ever
    exported, which is enough to render - so a job file that has been truncated
    or deleted is recoverable rather than a re-review from scratch.

    What it cannot bring back is the OCR's own line and word geometry, so a
    rebuilt block falls back to reading its alignment off the ink and to using
    its box as the erase mask. Existing entries are never touched: this only
    fills in what is missing.
    """
    from util.imagetools.job import CONFIRMED, TRANSLATED, ImageEntry, TextBlock

    source = _newest_source(job, path)
    data = _load(source)
    images = blocks = 0
    for item in data.get("images") or []:
        if not isinstance(item, dict):
            continue
        relpath = str(item.get("image") or "")
        if not relpath:
            continue
        if not (Path(job.root) / relpath).is_file():
            continue                      # the image itself is gone
        existing = None
        try:
            existing = job.find(relpath)
        except JobError:
            pass
        if existing is not None and existing.blocks:
            continue                      # real work here; leave it alone
        # An entry with no blocks is not "already fine". Opening the editor
        # re-adds a lost image as an empty shell before anything else runs, so
        # skipping on presence alone would leave the shell and restore nothing.
        entry = existing or ImageEntry(relpath, int(item.get("index") or 0))
        for record in item.get("regions") or []:
            if not isinstance(record, dict) or "box" not in record:
                continue
            block = TextBlock(
                str(record.get("id") or ""),
                Box.from_any(record["box"]),
                str(record.get("source") or ""),
                str(record.get("target") or ""),
                -90.0 if record.get("orientation") == "vertical" else 0.0,
            )
            if not block.block_id:
                continue
            entry.blocks.append(block)
            blocks += 1
        if not entry.blocks:
            continue
        entry.status = (
            TRANSLATED
            if any(b.target_text.strip() for b in entry.blocks)
            else CONFIRMED
        )
        if existing is None:
            job.images.append(entry)
        images += 1
    if images:
        job.images.sort(key=lambda e: e.relpath)
        for index, entry in enumerate(job.images):
            entry.index = index
    return images, blocks


def summarise(result: ImportResult) -> list[str]:
    lines = []
    if result.source is not None:
        lines.append(f"Read {result.source}")
    lines.append(
        f"Applied {result.applied} translation(s) across {result.images} image(s)."
    )
    for label, items in (
        ("left blank", result.empty),
        ("not in the file", result.missing),
        ("unknown to this job", result.unknown),
    ):
        if items:
            shown = ", ".join(items[:6])
            more = f" (+{len(items) - 6} more)" if len(items) > 6 else ""
            lines.append(f"  {len(items)} {label}: {shown}{more}")
    return lines
