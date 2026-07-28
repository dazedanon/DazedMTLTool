"""Deterministically rewrap existing RPG Maker MV/MZ/Ace translations.

This module operates on an RPG Maker JSON data directory without calling a
translation provider.  It only touches known display fields and never edits
``_original``.
"""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from util import dazedwrap


DIALOGUE = "dialogue"
FACE_DIALOGUE = "face_dialogue"
LIST_HELP = "list"
NOTES = "notes"

ALL_CATEGORIES = frozenset({DIALOGUE, FACE_DIALOGUE, LIST_HELP, NOTES})
SUPPORTED_EVENT_CODES = frozenset({122, 324, 325, 357, 401, 405})
STANDARD_MESSAGE_CODES = frozenset({401, 405})

_LIST_FIELDS_BY_FILE = {
    "Actors.json": ("profile",),
    "Armors.json": ("description",),
    "Items.json": ("description",),
    "Skills.json": ("description",),
    "States.json": ("description",),
    "Weapons.json": ("description",),
}

# These are the note bodies the translation module itself treats as wrapped
# player-facing prose.  Match only the captured body so plugin tags stay exact.
_NOTE_BODY_PATTERNS: tuple[tuple[re.Pattern[str], bool], ...] = (
    (re.compile(r"<SG説明:\n?(.*?)>", re.DOTALL), True),
    (
        re.compile(r"<SG説明:.+?Client\s?:.+?\n\n(.*?)>", re.DOTALL),
        True,
    ),
    (re.compile(r"<sub_[123]:([^>]+)", re.DOTALL), False),
    (re.compile(r"<infowindow:(.*?)>", re.DOTALL), False),
    (re.compile(r"<ExtendDesc:(.*?)>", re.DOTALL), False),
    (re.compile(r"<ClassMessage>\n?(.*?)</ClassMessage>", re.DOTALL), False),
    (re.compile(r"<コメント:\n?(.*?)>", re.DOTALL), False),
)

_SPEAKER_LINE = re.compile(
    r"^(?P<prefix>(?:\[[^\]\n]{1,100}\]|"
    r"(?:[\\]+[kKnN][wWcCrReE]?[\[<][^\]>\n]+[\]>]))\n)"
)


@dataclass(frozen=True)
class RewrapOptions:
    dialogue_width: int
    face_dialogue_width: int
    list_width: int
    note_width: int
    categories: frozenset[str] = ALL_CATEGORIES
    event_codes: frozenset[int] | None = STANDARD_MESSAGE_CODES
    max_protected_rows: int = 4
    skip_protected_overflow: bool = True

    def __post_init__(self) -> None:
        for label, value in (
            ("dialogue_width", self.dialogue_width),
            ("face_dialogue_width", self.face_dialogue_width),
            ("list_width", self.list_width),
            ("note_width", self.note_width),
        ):
            if int(value) <= 0:
                raise ValueError(f"{label} must be positive")
        unknown = set(self.categories) - set(ALL_CATEGORIES)
        if unknown:
            raise ValueError(f"Unknown rewrap categories: {sorted(unknown)}")
        unsupported_codes = set(self.event_codes or ()) - set(SUPPORTED_EVENT_CODES)
        if unsupported_codes:
            supported = ", ".join(str(code) for code in sorted(SUPPORTED_EVENT_CODES))
            raise ValueError(
                f"Unsupported event code(s): {sorted(unsupported_codes)}. "
                f"Supported display codes: {supported}"
            )
        if self.max_protected_rows < 0:
            raise ValueError("max_protected_rows cannot be negative")

    def width_for(self, category: str) -> int:
        return {
            DIALOGUE: self.dialogue_width,
            FACE_DIALOGUE: self.face_dialogue_width,
            LIST_HELP: self.list_width,
            NOTES: self.note_width,
        }[category]


@dataclass(frozen=True)
class RewrapPreview:
    file_name: str
    category: str
    locator: str
    code: int | None
    before: str
    after: str
    rows: int
    overflow: bool = False

    def summary(self, limit: int = 150) -> str:
        code = f"code {self.code}" if self.code is not None else "database"
        text = re.sub(r"\s+", " ", self.after).strip()
        if len(text) > limit:
            text = text[: limit - 1] + "…"
        warning = " · exceeds row limit" if self.overflow else ""
        return (
            f"{self.file_name} · {self.category} · {code} · {self.rows} row(s)"
            f"{warning}\n{self.locator} — {text}"
        )


@dataclass
class RewrapReport:
    files_scanned: int = 0
    files_with_changes: int = 0
    files_written: int = 0
    changes_found: int = 0
    changes_applied: int = 0
    overflow_skipped: int = 0
    previews: list[RewrapPreview] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    by_category: Counter[str] = field(default_factory=Counter)
    by_code: Counter[int] = field(default_factory=Counter)

    def headline(self, *, apply: bool) -> str:
        action = (
            f"Applied {self.changes_applied} change(s) in {self.files_written} file(s)"
            if apply
            else f"Found {self.changes_found} change(s) in {self.files_with_changes} file(s)"
        )
        suffix = f"; skipped {self.overflow_skipped} row overflow(s)" if self.overflow_skipped else ""
        return f"{action}; scanned {self.files_scanned} file(s){suffix}."


class _Collector:
    def __init__(
        self,
        report: RewrapReport,
        file_name: str,
        *,
        apply: bool,
        preview_limit: int,
        options: RewrapOptions,
    ) -> None:
        self.report = report
        self.file_name = file_name
        self.apply = apply
        self.preview_limit = preview_limit
        self.options = options
        self.file_has_change = False
        self.file_dirty = False

    def offer(
        self,
        *,
        category: str,
        locator: str,
        code: int | None,
        before: str,
        after: str,
        row_limited: bool = False,
    ) -> bool:
        if before == after:
            return False
        rows = _rendered_rows(after)
        overflow = bool(
            row_limited
            and self.options.max_protected_rows
            and rows > self.options.max_protected_rows
        )
        self.file_has_change = True
        self.report.changes_found += 1
        self.report.by_category[category] += 1
        if code is not None:
            self.report.by_code[code] += 1
        if len(self.report.previews) < self.preview_limit:
            self.report.previews.append(
                RewrapPreview(
                    file_name=self.file_name,
                    category=category,
                    locator=locator,
                    code=code,
                    before=before,
                    after=after,
                    rows=rows,
                    overflow=overflow,
                )
            )
        if overflow and self.options.skip_protected_overflow:
            self.report.overflow_skipped += 1
            return False
        if not self.apply:
            return False
        self.file_dirty = True
        self.report.changes_applied += 1
        return True


def parse_event_codes(value: str) -> frozenset[int] | None:
    """Parse a comma/space separated event-code filter; blank means all supported."""
    text = str(value or "").strip()
    if not text:
        return None
    parts = [part for part in re.split(r"[\s,;]+", text) if part]
    try:
        codes = frozenset(int(part) for part in parts)
    except ValueError as exc:
        raise ValueError("Event codes must be integers separated by commas or spaces") from exc
    unsupported = set(codes) - set(SUPPORTED_EVENT_CODES)
    if unsupported:
        supported = ", ".join(str(code) for code in sorted(SUPPORTED_EVENT_CODES))
        raise ValueError(
            f"Unsupported event code(s): {sorted(unsupported)}. "
            f"Supported display codes: {supported}"
        )
    return codes


def rewrap_directory(
    directory: str | Path,
    options: RewrapOptions,
    *,
    file_names: Iterable[str] | None = None,
    apply: bool = False,
    preview_limit: int = 500,
) -> RewrapReport:
    """Scan or rewrap selected JSON files under *directory*.

    ``apply=False`` is a read-only preview.  Writes are atomic and only occur for
    files with accepted changes.
    """
    root = Path(directory)
    report = RewrapReport()
    if not root.is_dir():
        report.errors.append(f"Directory not found: {root}")
        return report

    if file_names is None:
        paths = sorted(root.glob("*.json"), key=lambda p: p.name.casefold())
    else:
        paths = []
        for name in sorted(set(file_names), key=str.casefold):
            candidate = Path(name)
            if candidate.name != str(name) or candidate.suffix.casefold() != ".json":
                report.errors.append(f"Invalid JSON filename: {name}")
                continue
            paths.append(root / candidate.name)

    for path in paths:
        if not path.is_file():
            report.errors.append(f"File not found: {path.name}")
            continue
        report.files_scanned += 1
        collector = _Collector(
            report,
            path.name,
            apply=apply,
            preview_limit=max(0, int(preview_limit)),
            options=options,
        )
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
            _rewrap_document(document, path.name, options, collector)
            if collector.file_has_change:
                report.files_with_changes += 1
            if apply and collector.file_dirty:
                _write_json_atomic(path, document)
                report.files_written += 1
        except Exception as exc:  # noqa: BLE001 - isolate malformed project files
            report.errors.append(f"{path.name}: {exc}")
    return report


def _rewrap_document(
    document,
    file_name: str,
    options: RewrapOptions,
    collector: _Collector,
) -> None:
    if LIST_HELP in options.categories:
        _rewrap_database_lists(document, file_name, options, collector)
    if NOTES in options.categories:
        _rewrap_note_bodies(document, options, collector)
    if DIALOGUE in options.categories or FACE_DIALOGUE in options.categories or LIST_HELP in options.categories:
        for commands, locator in _iter_command_lists(document):
            _rewrap_command_list(commands, locator, options, collector)


def _rewrap_database_lists(
    document,
    file_name: str,
    options: RewrapOptions,
    collector: _Collector,
) -> None:
    fields = _LIST_FIELDS_BY_FILE.get(file_name, ())
    if not fields or not isinstance(document, list):
        return
    for index, entry in enumerate(document):
        if not isinstance(entry, dict):
            continue
        for field_name in fields:
            before = entry.get(field_name)
            if not isinstance(before, str) or not before.strip():
                continue
            after = _rewrap_text(before, options.list_width)
            if collector.offer(
                category=LIST_HELP,
                locator=f"/{index}/{field_name}",
                code=None,
                before=before,
                after=after,
                row_limited=True,
            ):
                entry[field_name] = after


def _iter_command_lists(node, locator: str = ""):
    if isinstance(node, dict):
        commands = node.get("list")
        if _looks_like_command_list(commands):
            yield commands, f"{locator}/list"
        for key, value in node.items():
            if key == "_original" or (key == "list" and commands is value):
                continue
            yield from _iter_command_lists(value, f"{locator}/{_pointer_part(key)}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _iter_command_lists(value, f"{locator}/{index}")


def _looks_like_command_list(value) -> bool:
    return isinstance(value, list) and any(
        isinstance(item, dict) and isinstance(item.get("code"), int)
        for item in value
    )


def _rewrap_command_list(
    commands: list,
    locator: str,
    options: RewrapOptions,
    collector: _Collector,
) -> None:
    i = 0
    face_pending = False
    while i < len(commands):
        command = commands[i]
        if not isinstance(command, dict):
            face_pending = False
            i += 1
            continue
        code = command.get("code")
        if code == 101:
            face_pending = _code101_has_face(command)
            i += 1
            continue
        if code in (401, 405):
            end = i + 1
            while end < len(commands):
                next_command = commands[end]
                if not isinstance(next_command, dict) or next_command.get("code") != code:
                    break
                end += 1
            category = FACE_DIALOGUE if code == 401 and face_pending else DIALOGUE
            face_pending = False
            if category in options.categories and _event_code_enabled(options, code):
                entries = [
                    (index, item["parameters"][0])
                    for index, item in enumerate(commands[i:end], start=i)
                    if isinstance(item.get("parameters"), list)
                    and item.get("parameters")
                    and isinstance(item["parameters"][0], str)
                ]
                if entries:
                    before_parts = [text for _index, text in entries]
                    if code == 401:
                        # A 401 is an RPG Maker command boundary, not a rendered row.
                        # Preserve every command and wrap only inside its text value.
                        after_parts = [
                            _rewrap_text(text, options.width_for(category))
                            for text in before_parts
                        ]
                    else:
                        after_parts = [
                            _rewrap_text(
                                "\n".join(before_parts), options.width_for(category)
                            )
                        ]
                    before = "\n".join(before_parts)
                    after = "\n".join(after_parts)
                    accepted = collector.offer(
                        category=category,
                        locator=f"{locator}/{i}/parameters/0",
                        code=code,
                        before=before,
                        after=after,
                        row_limited=(code != 401),
                    )
                    if accepted:
                        if code == 401:
                            for (index, _text), wrapped in zip(entries, after_parts):
                                commands[index]["parameters"][0] = wrapped
                        else:
                            end = _assign_scrolling_text_lines(
                                commands, i, end, after
                            )
            i = end
            continue

        if code not in (-1, 0):
            face_pending = False

        if _event_code_enabled(options, code):
            if code == 122 and LIST_HELP in options.categories:
                _rewrap_code122(command, f"{locator}/{i}", options, collector)
            elif code == 324 and LIST_HELP in options.categories:
                _rewrap_string_parameter(
                    command,
                    1,
                    LIST_HELP,
                    f"{locator}/{i}",
                    options.list_width,
                    collector,
                )
            elif code == 325 and DIALOGUE in options.categories:
                _rewrap_string_parameter(
                    command,
                    1,
                    DIALOGUE,
                    f"{locator}/{i}",
                    options.dialogue_width,
                    collector,
                )
            elif code == 357 and DIALOGUE in options.categories:
                _rewrap_code357(command, f"{locator}/{i}", options, collector)
        i += 1


def _assign_scrolling_text_lines(
    commands: list,
    start: int,
    end: int,
    text: str,
) -> int:
    """Store wrapped scrolling-text rows as native 405 continuation commands."""
    lines = text.split("\n")
    existing = end - start
    for offset, line in enumerate(lines):
        target = start + offset
        if offset >= existing:
            template = copy.deepcopy(commands[end - 1])
            template.pop("_original", None)
            template["code"] = 405
            template["parameters"] = [line]
            commands.insert(target, template)
            end += 1
        else:
            commands[target]["code"] = 405
            commands[target]["parameters"] = [line]
    for target in range(start + len(lines), end):
        commands[target]["code"] = -1
        commands[target]["parameters"] = []
    return end


def _rewrap_string_parameter(
    command: dict,
    parameter_index: int,
    category: str,
    locator: str,
    width: int,
    collector: _Collector,
) -> None:
    params = command.get("parameters")
    if not isinstance(params, list) or parameter_index >= len(params):
        return
    before = params[parameter_index]
    if not isinstance(before, str) or not before.strip():
        return
    after = _rewrap_text(before, width)
    if collector.offer(
        category=category,
        locator=f"{locator}/parameters/{parameter_index}",
        code=command.get("code"),
        before=before,
        after=after,
        row_limited=True,
    ):
        params[parameter_index] = after


def _rewrap_code122(
    command: dict,
    locator: str,
    options: RewrapOptions,
    collector: _Collector,
) -> None:
    params = command.get("parameters")
    if not isinstance(params, list) or len(params) <= 4 or not isinstance(params[4], str):
        return
    before = params[4]
    first_tick = before.find("`")
    last_tick = before.rfind("`")
    if first_tick < 0 or last_tick <= first_tick:
        return
    body = before[first_tick + 1 : last_tick]
    # Reflow only line breaks previously inserted by list wrapping.  Keep RPG
    # Maker name codes such as \n[1] intact.
    normalized = re.sub(r"\\n(?!\[)", " ", body)
    wrapped = _rewrap_text(normalized, options.list_width).replace("\n", r"\n")
    after = before[: first_tick + 1] + wrapped + before[last_tick:]
    if collector.offer(
        category=LIST_HELP,
        locator=f"{locator}/parameters/4",
        code=122,
        before=before,
        after=after,
        row_limited=True,
    ):
        params[4] = after


def _rewrap_code357(
    command: dict,
    locator: str,
    options: RewrapOptions,
    collector: _Collector,
) -> None:
    params = command.get("parameters")
    if not isinstance(params, list) or len(params) <= 3 or not isinstance(params[3], dict):
        return
    payload = params[3]
    for key in ("comment", "text", "messageText"):
        before = payload.get(key)
        if not isinstance(before, str) or not before.strip():
            continue
        after = _rewrap_text(before, options.dialogue_width)
        if collector.offer(
            category=DIALOGUE,
            locator=f"{locator}/parameters/3/{_pointer_part(key)}",
            code=357,
            before=before,
            after=after,
            row_limited=True,
        ):
            payload[key] = after


def _rewrap_note_bodies(document, options: RewrapOptions, collector: _Collector) -> None:
    for owner, locator in _iter_note_owners(document):
        note = owner.get("note")
        if not isinstance(note, str) or not note.strip():
            continue
        edits: list[tuple[int, int, str]] = []
        occupied: list[tuple[int, int]] = []
        for pattern, structured in _NOTE_BODY_PATTERNS:
            for match in pattern.finditer(note):
                start, end = match.span(1)
                if any(start < used_end and end > used_start for used_start, used_end in occupied):
                    continue
                before = match.group(1)
                if not before.strip():
                    continue
                after = (
                    dazedwrap.wrapSGDesc(before, options.note_width)
                    if structured
                    else _rewrap_text(before, options.note_width)
                )
                if collector.offer(
                    category=NOTES,
                    locator=f"{locator}/note[{start}:{end}]",
                    code=None,
                    before=before,
                    after=after,
                    row_limited=True,
                ):
                    edits.append((start, end, after))
                occupied.append((start, end))
        for start, end, replacement in sorted(edits, reverse=True):
            note = note[:start] + replacement + note[end:]
        if edits:
            owner["note"] = note


def _iter_note_owners(node, locator: str = ""):
    if isinstance(node, dict):
        if isinstance(node.get("note"), str):
            yield node, locator
        for key, value in node.items():
            if key == "_original":
                continue
            yield from _iter_note_owners(value, f"{locator}/{_pointer_part(key)}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _iter_note_owners(value, f"{locator}/{index}")


def _rewrap_text(text: str, width: int) -> str:
    if not text:
        return text
    prefix = ""
    body = text
    prefix_match = _SPEAKER_LINE.match(body)
    if prefix_match:
        prefix = prefix_match.group("prefix")
        body = body[len(prefix) :]
    uses_br = "<br>" in body and "\n" not in body
    if uses_br:
        body = body.replace("<br>", " ")
    wrapped = dazedwrap.wrapText(body, int(width))
    if uses_br:
        wrapped = wrapped.replace("\n", "<br>")
    return prefix + wrapped


def _rendered_rows(text: str) -> int:
    if not text:
        return 0
    body = text
    prefix_match = _SPEAKER_LINE.match(body)
    if prefix_match and not prefix_match.group("prefix").lstrip().startswith("["):
        # Name-window controls do not consume a message-body row.  A literal
        # [Speaker] first line does, so keep that line in the count.
        body = body[len(prefix_match.group("prefix")) :]
    return len(re.split(r"\n|<br>", body))


def _event_code_enabled(options: RewrapOptions, code) -> bool:
    if not isinstance(code, int) or code not in SUPPORTED_EVENT_CODES:
        return False
    return options.event_codes is None or code in options.event_codes


def _code101_has_face(command: dict) -> bool:
    params = command.get("parameters") or []
    return (
        len(params) >= 4
        and isinstance(params[0], str)
        and bool(params[0].strip())
    )


def _pointer_part(value) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _write_json_atomic(path: Path, document) -> None:
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.rewrap-",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=4)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        try:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        except OSError:
            pass
