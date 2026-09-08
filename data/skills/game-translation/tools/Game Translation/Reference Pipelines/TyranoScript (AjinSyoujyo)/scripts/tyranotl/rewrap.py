"""Fix the ways English breaks a message the Japanese laid out by hand.

TyranoScript joins consecutive scenario lines into one run of text and breaks it
only where the author wrote ``[r]``. Japanese needs no space between words and
sets about half as wide as the English that replaces it, so translating the text
without touching the layout produces three faults.

None of this belongs in ``inject``, which stays a mechanical span splice:
injecting a unit's own source has to reproduce the file byte for byte, and that
is what ``tl.py selftest`` checks. These are edits to the English, applied after.

**Glued words.** Two text lines in a row concatenate with nothing between them::

    ...an entirely different physiology.They sustain their vital functions...

A trailing space cannot fix it: ``parseScenario`` runs ``$.trim()`` on every line
before it looks at anything, and jQuery's ``rtrim`` takes U+00A0 with it, so a
non-breaking space is eaten too. What survives is KAG's own marker - a leading
``_`` is stripped *after* the trim, so ``_ and Lewdness...`` keeps its space.
That is what this pass writes.

**Split words.** ``[ruby]`` attaches its reading to the *next character only*,
which is right for a kanji and wrong for a word. ``[ruby text="ザーメン"]精液``
is 精液 glossed with its slangy reading; both halves translate to "semen", so
the tag survives only to break the word in two - "s" wearing the ruby and "emen"
left behind::

    could I have some   s emen?

A gloss whose reading and base come out as the same word carries nothing, so the
tag goes and the base text stands on its own.

**Lines set flush to the measure.** English runs long, and a run that lands
between 95% and 100% of the box comes out as one line filling the measure edge
to edge, with nothing to show it is a full line rather than a clipped one::

    ...someone in my family taught me that kind of thing. It's not really my own true natu

That one is 1789px in an 1800px box - it fits, by eleven pixels, which is inside
the error of any measurement made outside the browser. Splitting it at the word
boundary nearest the middle gives two half-width lines instead, which read as
deliberate and cannot be pushed over the edge by a rounding difference. The
break is only inserted where the run would otherwise be a *single* line: a run
that already wraps is left to the engine, which balances it better than a fixed
rule could.

**A beat with nothing else on the line.** ``______[p]`` is the author's
trailing-off marker standing alone as a whole message. It carries no Japanese,
so the extractor never took it as a unit and ``polish`` never saw it; the line
reaches the screen as a row of underscores where English wants an ellipsis.
Converted here because this is the only pass that sees lines rather than units.

**Orphaned fragments.** A hand-placed ``[r]`` behind a line that now overflows
turns the overflow into an orphan of a word or two on a line of its own::

    Affection rises through physical contact and using
    the syringe,
    and Lewdness rises when you have sex.

Deleting that ``[r]`` lets the engine wrap the paragraph as a whole, which fills
both lines. Removing a break can only ever reduce the line count, never raise
it, so this is safe against a message box that is only three lines tall.

Three things have to be right for the overflow measurement to mean anything.

**Which box.** ``show_mesS`` is 1210px wide against ``show_mesL``/``H``/``T`` at
1920, so the same sentence wraps in one and not the other. The macros are parsed
out of ``system/macro.ks`` rather than hard-coded, and each file is scanned
forward tracking the last one called. A file that calls none of them - hint.ks
is one - inherits its caller's box, so unresolved files fall back to the
narrowest. That is the safe way to be wrong: the engine re-wraps a paragraph
whose break was removed, but nothing puts back an orphan.

**Which font.** ``mfrules`` in ``tyrano/css/font.css`` resolves to Source Han
Serif JP, shipped twice as ``MyFont1.otf`` and ``MyFont2.woff``; they are the
same face at the same units-per-em, so measuring the otf is measuring what the
player sees. The size comes from ``[deffont size=]``.

**What counts as one visual line.** Text accumulates across tags and across
source lines until an ``[r]``, ``[lr]``, ``[p]`` or ``[l]``. Inline emitters
(``[emb]``, ``[name2]`` …) stand in for a word at runtime and are measured as
one. Anything that makes the run discontinuous - a branch, a jump, a screen
clear - discards the buffer instead of measuring it, because the two halves may
never be on screen together.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import codes, layout

#: used when a file never names a box and no caller could be resolved
NARROWEST = "show_mesS"

#: tags that end a visual line
BREAKS = {"r", "lr"}
#: tags that end the whole message
STOPS = {"p", "l"}
#: tags after which the text so far is not reliably one continuous run
DISCARDS = {"if", "elsif", "else", "endif", "jump", "call", "return",
            "cm", "ct", "er", "s", "clearfix", "clearstack", "macro", "endmacro"}

#: what an inline emitter is worth when measured: it expands to a name or a body
#: part at runtime, so a short word rather than nothing
EMITTER_STANDIN = "Koko"

MACRO_CALL_RE = re.compile(r"\[(show_mes[A-Z]?)\]")
JUMP_RE = re.compile(r'storage\s*=\s*"([^"]+\.ks)"')

#: a following line opening with one of these is a list item or a quoted speech
#: turn, where the author's break carries meaning the width does not
KEEP_AFTER = ("・", "※", "→", "-", "*", "「", "『", "＊")

#: a single line wider than this fraction of its box is set flush to the
#: measure and gets split in two
FLUSH = 0.95

#: a whole line that is only the author's trailing-off marker, which carries no
#: Japanese and so was never extracted as a unit
LONE_MARKER_RE = re.compile(r"^([\uff3f_]{2,})(?=(?:\[[^\]]*\])*\s*$)")

#: tags that carry nothing once the text is English
DROPPED_TAGS = ("ruby",)
DROPPED_RE = re.compile(r"\[(?:" + "|".join(DROPPED_TAGS) + r")(?:\s[^\]]*)?\]")

#: characters either side of a junction that mean a space belongs there. Kana and
#: kanji never take one, and neither does a run that already has one.
WORD_END = re.compile(r"[0-9A-Za-z,.!?;:)\]\"'♡♪…-]$")
WORD_START = re.compile(r"[0-9A-Za-z(\[\"'-]")


@dataclass
class Box:
    name: str
    width: int          # px available to text, after the margins


@dataclass
class Cut:
    """A break tag to drop.

    ``[r]`` is deleted outright. ``[lr]`` also waits for a click, and that is
    pacing the author chose rather than layout the translation broke, so it is
    downgraded to ``[l]`` - the wait stays, the newline goes.
    """
    file: str
    line: int           # 1-based
    column: int         # offset of the tag within the line
    tag: str            # "r" or "lr"
    width: float        # measured width of the visual line in front of it
    box: str
    limit: int
    preview: str

    @property
    def old(self) -> str:
        return f"[{self.tag}]"

    @property
    def new(self) -> str:
        return "[l]" if self.tag == "lr" else ""


@dataclass
class Join:
    """A line that continues the one above and needs a space in front of it."""
    file: str
    line: int           # 1-based
    before: str
    after: str


@dataclass
class Split:
    """A break to insert, so one flush line becomes two half-width ones."""
    file: str
    line: int           # 1-based
    column: int         # where the break goes, within the line
    width: float
    box: str
    limit: int
    left: str
    right: str


@dataclass
class Drop:
    """A span to delete, or to swap for something shorter."""
    file: str
    line: int           # 1-based
    column: int         # offset of the span within the line
    old: str
    new: str = ""
    kind: str = "ruby"


@dataclass
class Plan:
    cuts: list[Cut] = field(default_factory=list)
    joins: list[Join] = field(default_factory=list)
    drops: list[Drop] = field(default_factory=list)
    splits: list[Split] = field(default_factory=list)


def message_boxes(app_root: Path) -> dict[str, Box]:
    """Parse the ``show_mes*`` macros for their text width."""
    path = app_root / "data" / "scenario" / "system" / "macro.ks"
    boxes: dict[str, Box] = {}
    current: str | None = None
    width = margin_l = margin_r = None
    for line in path.read_text(encoding="utf-8").splitlines():
        macro = re.match(r'\[macro name="(show_mes[A-Z]?)"\]', line.strip())
        if macro:
            current, width, margin_l, margin_r = macro.group(1), None, None, None
            continue
        if current is None:
            continue
        if line.strip() == "[endmacro]":
            if width:
                boxes[current] = Box(current, width - (margin_l or 0) - (margin_r or 0))
            current = None
            continue
        if "[position" not in line:
            continue
        found = re.search(r'\bwidth\s*=\s*"?(\d+)', line)
        if found and width is None:
            width = int(found.group(1))
        for key in ("marginl", "marginr"):
            found = re.search(rf"\b{key}\s*=\s*\"?(\d+)", line)
            if found:
                if key == "marginl":
                    margin_l = int(found.group(1))
                else:
                    margin_r = int(found.group(1))
    return boxes


def font_size(app_root: Path, default: int = 42) -> int:
    for path in sorted((app_root / "data" / "scenario").rglob("*.ks")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lstrip().startswith(";"):
                continue
            found = re.search(r"\[deffont[^\]]*\bsize\s*=\s*\"?(\d+)", line)
            if found:
                return int(found.group(1))
    return default


def _boxes_by_line(text: str, boxes: dict[str, Box], inherited: str) -> list[str]:
    out, current = [], inherited
    for line in text.splitlines():
        found = MACRO_CALL_RE.search(line)
        if found and found.group(1) in boxes:
            current = found.group(1)
        out.append(current)
    return out


def inherited_box(root: Path, target: Path, boxes: dict[str, Box]) -> str:
    """The box a file that never sets one is entered with, resolved one level."""
    name = target.name
    seen: set[str] = set()
    for path in sorted(root.rglob("*.ks")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if name not in text:
            continue
        current = None
        for line in text.splitlines():
            found = MACRO_CALL_RE.search(line)
            if found and found.group(1) in boxes:
                current = found.group(1)
            if current and any(ref.endswith(name) for ref in JUMP_RE.findall(line)):
                seen.add(current)
    return seen.pop() if len(seen) == 1 else NARROWEST


def _plain(text: str) -> str:
    """Message text with the HTML the scripts embed taken out."""
    return codes.HTML_RE.sub("", text)


def scan(root: Path, app_root: Path, emitters: set[str]) -> Plan:
    """Walk every script's message runs, collecting the breaks and the junctions."""
    boxes = message_boxes(app_root)
    if not boxes:
        return Plan()
    size = font_size(app_root)
    plan = Plan()

    for path in sorted(root.rglob("*.ks")):
        text = path.read_text(encoding="utf-8", errors="replace")
        default = NARROWEST
        if not MACRO_CALL_RE.search(text):
            default = inherited_box(root, path, boxes)
        active = _boxes_by_line(text, boxes, default)
        lines = text.splitlines()
        rel = path.relative_to(root).as_posix()

        for number, line in enumerate(lines, 1):
            for tag in DROPPED_RE.finditer(line):
                plan.drops.append(Drop(rel, number, tag.start(), tag.group()))
            marker = LONE_MARKER_RE.match(line.strip())
            if marker:
                start = len(line) - len(line.lstrip())
                plan.drops.append(Drop(rel, number, start, marker.group(1),
                                      "...", "marker"))

        buffer = ""
        in_script = False
        for number, line in enumerate(lines, 1):
            stripped = line.strip()
            if "[iscript]" in stripped:
                in_script = True
            if in_script:
                if "[endscript]" in stripped:
                    in_script = False
                buffer = ""
                continue
            if not stripped or stripped[0] in (";", "*", "@"):
                if stripped[:1] in (";", "*", "@"):
                    buffer = ""
                continue

            body = stripped[1:] if stripped[0] == "_" else stripped
            offset = len(line) - len(line.lstrip()) + (1 if stripped[0] == "_" else 0)
            first_text = True
            cursor = 0
            line_start = len(buffer)
            #: (index in the accumulated text, length, index in this line)
            segments: list[tuple[int, int, int]] = []
            for tag in codes.TAG_RE.finditer(body):
                chunk = _plain(body[cursor:tag.start()])
                if chunk and first_text:
                    buffer = _maybe_join(plan, rel, number, buffer, chunk, stripped)
                    first_text = False
                if chunk:
                    segments.append((len(buffer), len(chunk), offset + cursor))
                buffer += chunk
                cursor = tag.end()
                name = tag.group(1)
                if name in BREAKS:
                    box = boxes.get(active[number - 1], boxes[NARROWEST])
                    width = layout.measure(buffer.strip(), size, app_root)
                    following = _following(lines, number, body[cursor:])
                    cutting = (buffer.strip() and width > box.width and following
                               and not following.startswith(KEEP_AFTER))
                    if cutting:
                        plan.cuts.append(Cut(rel, number, offset + tag.start(), name,
                                             width, box.name, box.width,
                                             buffer.strip()[:72]))
                        # the run carries on past a break we are about to drop,
                        # so whatever follows is measured - and spaced - as part
                        # of the same visual line
                        continue
                    buffer = ""
                    segments = []
                    first_text = True
                elif name in STOPS or name in DISCARDS:
                    box = boxes.get(active[number - 1], boxes[NARROWEST])
                    _flush(plan, rel, number, buffer, segments, box,
                           size, app_root, line_start)
                    buffer = ""
                    segments = []
                    first_text = True
                elif name in emitters:
                    buffer += EMITTER_STANDIN
                    first_text = False
            chunk = _plain(body[cursor:])
            if chunk and first_text:
                buffer = _maybe_join(plan, rel, number, buffer, chunk, stripped)
            buffer += chunk
    return plan


def _flush(plan: Plan, rel: str, number: int, buffer: str, segments: list,
           box: Box, size: int, app_root: Path, line_start: int) -> None:
    """Split a run that would be one line filling the measure.

    The break has to land on the line the run *ends* on, so only a run that both
    starts and ends on this line is a candidate - one spilling over several
    source lines is left alone rather than broken at a point this pass cannot
    address.

    The split point is an index into the accumulated *text*, and the line it has
    to be written into is text with tags threaded through it. ``segments`` is
    the map between the two, one entry per run of text between tags, so the
    break lands on a real space and never inside `[elsif exp="..."]`.
    """
    run = buffer.strip()
    if not run or line_start:
        return
    width = layout.measure(run, size, app_root)
    if not (box.width * FLUSH < width <= box.width):
        return
    words = run.split(" ")
    if len(words) < 4:
        return
    best = min(range(1, len(words)),
               key=lambda i: abs(layout.measure(" ".join(words[:i]), size, app_root)
                                 - width / 2))
    left, right = " ".join(words[:best]), " ".join(words[best:])

    lead = len(buffer) - len(buffer.lstrip())
    at = lead + len(left)                      # the space between the halves
    for text_at, length, line_at in segments:
        if text_at <= at < text_at + length:
            plan.splits.append(Split(rel, number, line_at + (at - text_at),
                                     width, box.name, box.width,
                                     left[-34:], right[:34]))
            return


def _maybe_join(plan: Plan, rel: str, number: int, buffer: str,
                chunk: str, stripped: str) -> str:
    """Record a junction if this line's first text glues onto the run above it."""
    if not buffer or stripped[0] == "_":
        return buffer
    if not WORD_END.search(buffer) or not WORD_START.match(chunk):
        return buffer
    plan.joins.append(Join(rel, number, buffer[-34:], chunk[:34]))
    return buffer + " "


def _following(lines: list[str], number: int, tail: str) -> str:
    """The text that would land on the line after the break, for the guard."""
    rest = codes.TAG_RE.sub("", tail).strip()
    if rest:
        return rest
    for line in lines[number:]:
        stripped = line.lstrip()
        if stripped.startswith((";", "*", "@")):
            return ""
        rest = codes.TAG_RE.sub("", line).strip().lstrip("_").strip()
        if rest:
            return rest
        if re.search(r"\[(?:p|l|jump|call|s)(?:\s[^\]]*)?\]", line):
            return ""
    return ""


def apply(root: Path, plan: Plan) -> tuple[int, int, int, int]:
    """Delete the marked breaks and mark the marked junctions, bottom-up."""
    edits: dict[str, list] = {}
    for cut in plan.cuts:
        edits.setdefault(cut.file, []).append(cut)
    for join in plan.joins:
        edits.setdefault(join.file, []).append(join)
    for drop in plan.drops:
        edits.setdefault(drop.file, []).append(drop)
    for split in plan.splits:
        edits.setdefault(split.file, []).append(split)

    cut_count = join_count = split_count = 0
    counts = {"ruby": 0, "marker": 0}
    for rel, group in edits.items():
        path = root / rel
        lines = path.read_bytes().decode("utf-8").split("\n")
        # bottom-up, and a Cut before a Join on the same line so the column holds
        for edit in sorted(group, key=lambda e: (-e.line, -getattr(e, "column", -1))):
            line = lines[edit.line - 1]
            if isinstance(edit, Split):
                head, tail = line[:edit.column], line[edit.column:]
                line = head.rstrip(" ") + "[r]" + tail.lstrip(" ")
                split_count += 1
            elif isinstance(edit, Drop):
                if line[edit.column:edit.column + len(edit.old)] != edit.old:
                    raise SystemExit(
                        f"{rel}:{edit.line}: no {edit.old} at column {edit.column}")
                line = line[:edit.column] + edit.new + line[edit.column + len(edit.old):]
                counts[edit.kind] += 1
            elif isinstance(edit, Cut):
                if line[edit.column:edit.column + len(edit.old)] != edit.old:
                    raise SystemExit(
                        f"{rel}:{edit.line}: no {edit.old} at column {edit.column}")
                head = line[:edit.column] + edit.new
                tail = line[edit.column + len(edit.old):]
                # a mid-line break often had a space on both sides; collapse the
                # pair at the junction only - some lines space their columns out
                # with runs of spaces on purpose
                if head.endswith(" ") and tail.startswith(" "):
                    tail = tail[1:]
                elif (WORD_END.search(head) and WORD_START.match(tail)):
                    head += " "          # the break was the only separator
                line = head + tail
                cut_count += 1
            else:
                indent = len(line) - len(line.lstrip())
                line = line[:indent] + "_ " + line[indent:]
                join_count += 1
            lines[edit.line - 1] = line
        path.write_bytes("\n".join(lines).encode("utf-8"))
    return cut_count, join_count, counts["ruby"], split_count, counts["marker"]
