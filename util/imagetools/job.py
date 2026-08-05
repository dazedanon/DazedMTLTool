"""The durable record of an image translation run.

One JSON file under the editable image workspace holds every image, every text
block found in it, and where each image has got to. It is the only thing that
survives closing the dialog, so it is written on a debounce rather than behind
a Save button - the reference workflow this is modelled on lost edits to an
explicit save exactly once, which is once too often.

Status is per image, not per job, so a two-hundred-image game can be reviewed
across several sittings without losing the place:

    pending -> needs_review -> confirmed -> translated -> rendered
                    ^              |
                    +--- edit -----+        (confirming is not final)

Only ``confirmed`` images are exported for translation. That gate is the whole
point of the semi-manual workflow: nothing reaches the translator that a human
has not looked at.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from util.imagetools.geometry import Box
from util.imagetools.ocr import Block, Line, Reading, Word
from util.imagetools.style import Style

FORMAT_VERSION = 4
JOB_DIRNAME = ".dazedtl"
JOB_FILENAME = "image_job.json"
ORIGINAL_DIRNAME = "original"

PENDING = "pending"
NEEDS_REVIEW = "needs_review"
CONFIRMED = "confirmed"
TRANSLATED = "translated"
RENDERED = "rendered"
ERROR = "error"

# Statuses whose text has been through a human.
REVIEWED = {CONFIRMED, TRANSLATED, RENDERED}


class JobError(RuntimeError):
    pass


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class TextBlock:
    """One translatable region: what it says, where it is, how sure we are."""

    block_id: str
    box: Box
    source_text: str = ""
    target_text: str = ""
    angle: float = 0.0
    lines: list[Line] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    skip: bool = False              # user marked it "leave this alone"
    # How the source text looked, measured from the pixels. None until the
    # block reaches the render step; kept afterwards because it holds the
    # user's corrections as well as the measurements.
    style: Style | None = None

    @property
    def vertical(self) -> bool:
        return abs(abs(self.angle) - 90.0) < 30.0

    @property
    def line_count(self) -> int:
        return max(1, len(self.lines))

    def to_dict(self) -> dict:
        data = {
            "id": self.block_id,
            "box": self.box.as_xywh(),
            "angle": round(self.angle, 2),
            "source": self.source_text,
            "target": self.target_text,
            "lines": [line.to_dict() for line in self.lines],
            "flags": list(self.flags),
            "skip": self.skip,
        }
        if self.style is not None:
            data["style"] = self.style.to_dict()
        return data

    @staticmethod
    def from_dict(data: dict) -> "TextBlock":
        return TextBlock(
            str(data.get("id") or _new_id()),
            Box.from_any(data["box"]),
            str(data.get("source") or ""),
            str(data.get("target") or ""),
            float(data.get("angle") or 0.0),
            [Line.from_dict(item) for item in data.get("lines") or []],
            [str(flag) for flag in data.get("flags") or []],
            bool(data.get("skip")),
            Style.from_dict(data["style"]) if data.get("style") else None,
        )

    @staticmethod
    def from_block(block: Block) -> "TextBlock":
        return TextBlock(
            _new_id(), block.box, block.text, "", block.angle, list(block.lines)
        )


@dataclass
class ImageEntry:
    relpath: str
    index: int = 0
    width: int = 0
    height: int = 0
    status: str = PENDING
    engine: str = ""
    error: str = ""
    blocks: list[TextBlock] = field(default_factory=list)
    words: list[Word] = field(default_factory=list)

    @property
    def name(self) -> str:
        return Path(self.relpath).name

    def block(self, block_id: str) -> TextBlock:
        for block in self.blocks:
            if block.block_id == block_id:
                return block
        raise JobError(f"{self.relpath} has no block {block_id!r}")

    def translatable(self) -> list[TextBlock]:
        return [b for b in self.blocks if not b.skip and b.source_text.strip()]

    def adopt(self, reading: Reading) -> None:
        """Replace this image's blocks with a fresh reading."""
        self.blocks = [TextBlock.from_block(block) for block in reading.blocks]
        self.words = list(reading.words)
        self.engine = reading.engine
        self.error = ""
        self.status = NEEDS_REVIEW

    def to_dict(self) -> dict:
        return {
            "image": self.relpath,
            "index": self.index,
            "width": self.width,
            "height": self.height,
            "status": self.status,
            "engine": self.engine,
            "error": self.error,
            "blocks": [block.to_dict() for block in self.blocks],
            "words": [word.to_dict() for word in self.words],
        }

    @staticmethod
    def from_dict(data: dict) -> "ImageEntry":
        entry = ImageEntry(
            str(data.get("image") or ""),
            int(data.get("index") or 0),
            int(data.get("width") or 0),
            int(data.get("height") or 0),
            str(data.get("status") or PENDING),
            str(data.get("engine") or ""),
            str(data.get("error") or ""),
        )
        entry.blocks = [TextBlock.from_dict(item) for item in data.get("blocks") or []]
        entry.words = [Word.from_dict(item) for item in data.get("words") or []]
        return entry


@dataclass
class Job:
    root: Path
    language: str = "English"
    images: list[ImageEntry] = field(default_factory=list)

    # ---------------------------------------------------------------- paths
    @property
    def work(self) -> Path:
        return Path(self.root) / JOB_DIRNAME

    @property
    def path(self) -> Path:
        return self.work / JOB_FILENAME

    def image_path(self, entry: ImageEntry) -> Path:
        return Path(self.root) / entry.relpath

    def original_path(self, entry: ImageEntry) -> Path:
        return self.work / ORIGINAL_DIRNAME / entry.relpath

    def source_path(self, entry: ImageEntry) -> Path:
        """Where to read this image's *untranslated* pixels from.

        Rendering writes over the editable PNG, because that is the file the
        Images tab patches back into the game. So the first render stashes the
        original here, and every render after that starts from it - otherwise
        the second pass would erase text that is already English and redraw it
        on top of itself, and the third would be worse.
        """
        original = self.original_path(entry)
        return original if original.is_file() else self.image_path(entry)

    # ---------------------------------------------------------------- access
    def find(self, relpath: str) -> ImageEntry:
        wanted = str(relpath).replace("\\", "/").lower()
        for entry in self.images:
            if entry.relpath.replace("\\", "/").lower() == wanted:
                return entry
        raise JobError(f"No image {relpath!r} in this job")

    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for entry in self.images:
            tally[entry.status] = tally.get(entry.status, 0) + 1
        return tally

    def confirmed(self) -> list[ImageEntry]:
        return [e for e in self.images if e.status in REVIEWED]

    def sync(self, relpaths: list[str]) -> tuple[int, int]:
        """Add anything new, drop only what has left the disk.

        Returns ``(added, removed)``. *relpaths* is what the caller wants
        **opened**, which is not the same as what the job should **contain** -
        and conflating the two was destructive. The Images tab passes the
        highlighted rows, so highlighting one image and pressing "Edit text..."
        used to delete every other image's boxes, corrected text and
        confirmations, and then autosave over them. An entry now survives
        unless its file is genuinely gone from the workspace.
        """
        wanted = {p.replace("\\", "/"): p for p in relpaths}
        by_key = {e.relpath.replace("\\", "/"): e for e in self.images}
        removed = [
            key for key in by_key
            if key not in wanted and not (Path(self.root) / by_key[key].relpath).is_file()
        ]
        for key in removed:
            self.images.remove(by_key[key])
        added = 0
        for key, original in wanted.items():
            if key not in by_key:
                self.images.append(ImageEntry(original))
                added += 1
        for index, entry in enumerate(sorted(self.images, key=lambda e: e.relpath)):
            entry.index = index
        self.images.sort(key=lambda e: e.index)
        return added, len(removed)

    # ---------------------------------------------------------------- io
    def to_dict(self) -> dict:
        return {
            "format": "dazedtl-image-job",
            "version": FORMAT_VERSION,
            "root": str(self.root),
            "language": self.language,
            "images": [entry.to_dict() for entry in self.images],
        }

    def save(self, path: Path | None = None) -> Path:
        target = Path(path) if path else self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        # Write beside the target and replace, so a crash mid-write cannot
        # leave a truncated job file - it is the only copy of the review work.
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(target)
        return target

    @staticmethod
    def load(root: Path) -> "Job":
        job = Job(Path(root))
        path = job.path
        if not path.is_file():
            return job
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JobError(f"{path} is not readable ({exc})") from exc
        job.language = str(data.get("language") or job.language)
        job.images = [ImageEntry.from_dict(item) for item in data.get("images") or []]
        return job


# -------------------------------------------------------------------- flags

FLAG_LABELS = {
    "overlap": "overlaps another block",
    "tiny": "too small to render legibly",
    "sparse": "almost no ink - may not be text",
    "single": "only one character",
    "punct": "punctuation only",
    "skew": "unusual rotation",
}


def review_flags(entry: ImageEntry, block: TextBlock, ink=None) -> list[str]:
    """Cheap deterministic reasons a block deserves a second look.

    The OCR engine reports no confidence, so this stands in for one. It is
    deliberately biased towards over-flagging: a false flag costs a glance,
    a missed one ships a mistake into the image.
    """
    flags = []
    box = block.box
    if min(box.w, box.h) < 8 or max(box.w, box.h) < 12:
        flags.append("tiny")

    for other in entry.blocks:
        if other.block_id != block.block_id and box.intersects(other.box):
            flags.append("overlap")
            break

    stripped = block.source_text.strip()
    if len(stripped) == 1:
        flags.append("single")
    elif stripped and not any(ch.isalnum() for ch in stripped):
        flags.append("punct")

    angle = abs(block.angle) % 180.0
    if min(angle, abs(angle - 90.0), abs(angle - 180.0)) > 5.0:
        flags.append("skew")

    if ink is not None and ink < 0.02:
        flags.append("sparse")
    return flags


def apply_flags(entry: ImageEntry) -> None:
    for block in entry.blocks:
        block.flags = review_flags(entry, block)
