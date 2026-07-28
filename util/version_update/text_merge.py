"""Conservative line-based three-way merging for plugins and text files."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class TextMergeResult:
    content: bytes | None
    conflicts: list[str]


@dataclass(frozen=True)
class _Edit:
    start: int
    end: int
    replacement: tuple[str, ...]
    side: str


def _decode(data: bytes) -> tuple[str, bool]:
    has_bom = data.startswith(b"\xef\xbb\xbf")
    return data.decode("utf-8-sig"), has_bom


def _edits(base: list[str], variant: list[str], side: str) -> list[_Edit]:
    result: list[_Edit] = []
    matcher = SequenceMatcher(a=base, b=variant, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            result.append(_Edit(i1, i2, tuple(variant[j1:j2]), side))
    return result


def _overlaps(left: _Edit, right: _Edit) -> bool:
    if left.start == left.end and right.start == right.end:
        return left.start == right.start
    if left.start == left.end:
        return right.start < left.start < right.end
    if right.start == right.end:
        return left.start < right.start < left.end
    return max(left.start, right.start) < min(left.end, right.end)


def merge_text_bytes(old: bytes, current: bytes, new: bytes) -> TextMergeResult:
    try:
        old_text, old_bom = _decode(old)
        current_text, current_bom = _decode(current)
        new_text, new_bom = _decode(new)
    except UnicodeDecodeError:
        return TextMergeResult(None, ["one or more versions are not valid UTF-8 text"])

    base_lines = old_text.splitlines(keepends=True)
    current_edits = _edits(base_lines, current_text.splitlines(keepends=True), "translated")
    new_edits = _edits(base_lines, new_text.splitlines(keepends=True), "upstream")
    conflicts: list[str] = []
    combined: list[_Edit] = list(current_edits)
    for upstream in new_edits:
        duplicate = False
        for translated in current_edits:
            if (
                upstream.start == translated.start
                and upstream.end == translated.end
                and upstream.replacement == translated.replacement
            ):
                duplicate = True
                break
            if _overlaps(upstream, translated):
                conflicts.append(
                    f"overlapping {translated.side}/{upstream.side} edits near old lines "
                    f"{min(translated.start, upstream.start) + 1}-"
                    f"{max(translated.end, upstream.end) + 1}"
                )
        if not duplicate:
            combined.append(upstream)
    if conflicts:
        return TextMergeResult(None, conflicts)

    merged = list(base_lines)
    for edit in sorted(combined, key=lambda item: (item.start, item.end), reverse=True):
        merged[edit.start : edit.end] = edit.replacement
    output = "".join(merged).encode("utf-8")
    if old_bom or current_bom or new_bom:
        output = b"\xef\xbb\xbf" + output
    return TextMergeResult(output, [])

