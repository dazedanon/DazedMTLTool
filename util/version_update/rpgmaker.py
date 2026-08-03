"""Semantic three-way JSON migration for RPG Maker MV/MZ game data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


_JAPANESE = re.compile(
    r"[\u3000-\u303f\u3040-\u309f\u30a0-\u30ff\u3400-\u4dbf"
    r"\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f]"
)
_MISSING = object()


@dataclass(frozen=True)
class SemanticIssue:
    path: str
    kind: str
    reason: str
    count: int = 1


@dataclass(frozen=True)
class SemanticMergeResult:
    content: bytes
    issues: list[SemanticIssue]

    @property
    def conflicts(self) -> list[SemanticIssue]:
        return [issue for issue in self.issues if issue.kind == "conflict"]

    @property
    def needs_translation(self) -> int:
        return sum(
            issue.count for issue in self.issues if issue.kind == "needs_translation"
        )

    @property
    def preserved_translations(self) -> int:
        return sum(
            issue.count
            for issue in self.issues
            if issue.kind == "preserved_translation"
        )


def is_supported_json_path(relative_path: str) -> bool:
    path = Path(relative_path)
    if path.suffix.lower() != ".json":
        return False
    parts = {part.lower() for part in path.parts[:-1]}
    if "data" not in parts:
        return False
    name = path.name.lower()
    return bool(
        re.fullmatch(r"map\d+\.json", name)
        or name
        in {
            "actors.json",
            "armors.json",
            "classes.json",
            "commonevents.json",
            "enemies.json",
            "items.json",
            "mapinfos.json",
            "skills.json",
            "scenario.json",
            "states.json",
            "system.json",
            "troops.json",
            "weapons.json",
        }
    )


def is_plugins_manifest_path(relative_path: str) -> bool:
    """Return whether a path is RPG Maker MV/MZ's generated plugin registry."""
    parts = tuple(part.lower() for part in Path(relative_path).parts)
    return parts in {("js", "plugins.js"), ("www", "js", "plugins.js")}


def _path_text(path: tuple[Any, ...]) -> str:
    result = "$"
    for part in path:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result += f".{part}"
    return result


def _has_japanese(value: Any) -> bool:
    return isinstance(value, str) and bool(_JAPANESE.search(value))


def _count_japanese(value: Any) -> int:
    if isinstance(value, str):
        return int(_has_japanese(value))
    if isinstance(value, list):
        return sum(_count_japanese(item) for item in value)
    if isinstance(value, dict):
        return sum(
            _count_japanese(item)
            for key, item in value.items()
            if key != "_original"
        )
    return 0


def _is_id_list(value: list[Any]) -> bool:
    rows = [item for item in value if item is not None]
    if not rows or not all(isinstance(item, dict) and "id" in item for item in rows):
        return False
    ids = [item["id"] for item in rows]
    return len(ids) == len(set(ids))


def _is_command_list(value: list[Any]) -> bool:
    rows = [item for item in value if item is not None]
    return bool(rows) and all(
        isinstance(item, dict) and "code" in item and "parameters" in item
        for item in rows
    )


def _skeleton(value: Any) -> Any:
    if isinstance(value, str):
        return "<text>"
    if isinstance(value, list):
        return tuple(_skeleton(item) for item in value)
    if isinstance(value, dict):
        return tuple(
            (key, _skeleton(item))
            for key, item in sorted(value.items())
            if key != "_original"
        )
    return value


def _freeze(value: Any) -> Any:
    """Preserve values while making nested JSON safe for matcher keys."""
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, dict):
        return tuple((key, _freeze(item)) for key, item in sorted(value.items()))
    return value


def _command_source_hint(command: dict[str, Any]) -> Any:
    parameters = command.get("parameters")
    if not isinstance(parameters, list):
        return None
    code = command.get("code")
    if code in {401, 405, 408} and parameters:
        return parameters[0]
    if code == 101:
        if len(parameters) > 4:
            return parameters[4]
        if 0 < len(parameters) < 4:
            return parameters[0]
    if code == 102 and parameters:
        return parameters[0]
    if code == 122 and len(parameters) > 4 and isinstance(parameters[4], str):
        matched = re.search(r"['\"`](.*)['\"`]", parameters[4])
        if matched:
            return matched.group(1)
    return None


def _command_signature(command: dict[str, Any], *, include_source: bool) -> tuple[Any, ...]:
    return (
        command.get("code"),
        command.get("indent"),
        _skeleton(command.get("parameters", [])),
        _freeze(_command_source_hint(command))
        if include_source
        else _skeleton(_command_source_hint(command)),
    )


@dataclass(frozen=True)
class _CommandUnit:
    """One event command, or one contiguous RPG Maker text block."""

    start: int
    stop: int
    code: Any
    indent: Any
    is_text: bool
    is_script: bool = False


def _command_units(commands: list[Any]) -> list[_CommandUnit]:
    """Group event commands whose physical shape translation may change."""
    units: list[_CommandUnit] = []
    index = 0
    while index < len(commands):
        command = commands[index]
        if not isinstance(command, dict):
            units.append(_CommandUnit(index, index + 1, None, None, False))
            index += 1
            continue
        code = command.get("code")
        indent = command.get("indent")
        parameters = command.get("parameters")
        if code == 355:
            stop = index + 1
            while stop < len(commands):
                following = commands[stop]
                if (
                    not isinstance(following, dict)
                    or following.get("code") != 655
                    or following.get("indent") != indent
                ):
                    break
                stop += 1
            units.append(_CommandUnit(index, stop, code, indent, False, True))
            index = stop
            continue
        if (
            code not in {401, 405, 408}
            or not isinstance(parameters, list)
            or not parameters
        ):
            units.append(_CommandUnit(index, index + 1, code, indent, False))
            index += 1
            continue
        stop = index + 1
        while stop < len(commands):
            following = commands[stop]
            if not isinstance(following, dict):
                break
            following_parameters = following.get("parameters")
            if (
                following.get("code") != code
                or following.get("indent") != indent
                or not isinstance(following_parameters, list)
                or not following_parameters
            ):
                break
            stop += 1
        units.append(_CommandUnit(index, stop, code, indent, True))
        index = stop
    return units


def _text_unit_source(
    commands: list[Any], unit: _CommandUnit, *, prefer_original: bool
) -> str:
    if prefer_original:
        for index in range(unit.start, unit.stop):
            command = commands[index]
            if not isinstance(command, dict):
                continue
            original = command.get("_original")
            if original is not None and not isinstance(original, (list, dict)):
                text = str(original)
                if text.strip():
                    return text
    parts: list[str] = []
    for index in range(unit.start, unit.stop):
        command = commands[index]
        if not isinstance(command, dict):
            continue
        parameters = command.get("parameters")
        if isinstance(parameters, list) and parameters:
            parts.append(str(parameters[0]))
    return "\n".join(parts)


def _command_unit_signature(
    commands: list[Any],
    unit: _CommandUnit,
    *,
    include_source: bool,
    prefer_original: bool,
) -> tuple[Any, ...]:
    if unit.is_text:
        source = _text_unit_source(
            commands, unit, prefer_original=prefer_original
        )
        return (
            "text-block",
            unit.code,
            unit.indent,
            _freeze(source) if include_source else "<text>",
        )
    if unit.is_script:
        source = commands[unit.start : unit.stop]
        return (
            "script-block",
            unit.indent,
            _freeze(source) if include_source else "<script>",
        )
    command = commands[unit.start]
    if isinstance(command, dict):
        return ("command",) + _command_signature(
            command, include_source=include_source
        )
    return ("other", _skeleton(command))


def _compatible_command_units(left: _CommandUnit, right: _CommandUnit) -> bool:
    if left.is_script or right.is_script:
        return left.is_script and right.is_script and left.indent == right.indent
    if left.is_text or right.is_text:
        return (
            left.is_text
            and right.is_text
            and left.code == right.code
            and left.indent == right.indent
        )
    return left.code == right.code and left.indent == right.indent


def _align_command_units(
    base: list[Any],
    variant: list[Any],
    *,
    translated_variant: bool,
) -> tuple[list[_CommandUnit], list[_CommandUnit], dict[int, int], list[int]]:
    """Align logical commands while using translated text-block metadata as source."""
    base_units = _command_units(base)
    variant_units = _command_units(variant)
    base_signatures = [
        _command_unit_signature(
            base,
            unit,
            include_source=not translated_variant or unit.is_text,
            prefer_original=False,
        )
        for unit in base_units
    ]
    variant_signatures = [
        _command_unit_signature(
            variant,
            unit,
            include_source=not translated_variant or unit.is_text,
            prefer_original=translated_variant and unit.is_text,
        )
        for unit in variant_units
    ]
    mapping: dict[int, int] = {}
    mapped_variant: set[int] = set()
    matcher = SequenceMatcher(a=base_signatures, b=variant_signatures, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                mapping[i1 + offset] = j1 + offset
                mapped_variant.add(j1 + offset)
        elif tag == "replace" and (i2 - i1) == (j2 - j1):
            for offset in range(i2 - i1):
                if _compatible_command_units(
                    base_units[i1 + offset], variant_units[j1 + offset]
                ):
                    mapping[i1 + offset] = j1 + offset
                    mapped_variant.add(j1 + offset)

    # Exact source matching deliberately stops at a changed text block. A
    # second structural pass lets that block align across nearby insertions or
    # deletions without weakening exact matches already established above.
    structural_base = [
        _command_unit_signature(
            base,
            unit,
            include_source=False,
            prefer_original=False,
        )
        for unit in base_units
    ]
    structural_variant = [
        _command_unit_signature(
            variant,
            unit,
            include_source=False,
            prefer_original=translated_variant and unit.is_text,
        )
        for unit in variant_units
    ]
    mapped_base = set(mapping)
    structural_matcher = SequenceMatcher(
        a=structural_base, b=structural_variant, autojunk=False
    )
    for tag, i1, i2, j1, j2 in structural_matcher.get_opcodes():
        if tag == "equal":
            pairs = zip(range(i1, i2), range(j1, j2))
        elif tag == "replace" and (i2 - i1) == (j2 - j1):
            pairs = zip(range(i1, i2), range(j1, j2))
        else:
            continue
        for base_index, variant_index in pairs:
            if base_index in mapped_base or variant_index in mapped_variant:
                continue
            if not _compatible_command_units(
                base_units[base_index], variant_units[variant_index]
            ):
                continue
            mapping[base_index] = variant_index
            mapped_base.add(base_index)
            mapped_variant.add(variant_index)
    return (
        base_units,
        variant_units,
        mapping,
        [index for index in range(len(variant_units)) if index not in mapped_variant],
    )


def _align_commands(
    base: list[Any], variant: list[Any], *, include_source: bool = False
) -> tuple[dict[int, int], list[int]]:
    if not include_source and len(base) == len(variant) and all(
        isinstance(left, dict)
        and isinstance(right, dict)
        and left.get("code") == right.get("code")
        and left.get("indent") == right.get("indent")
        for left, right in zip(base, variant)
    ):
        return {index: index for index in range(len(base))}, []
    base_signatures = [
        _command_signature(item, include_source=include_source)
        if isinstance(item, dict)
        else ("other", _skeleton(item))
        for item in base
    ]
    variant_signatures = [
        _command_signature(item, include_source=include_source)
        if isinstance(item, dict)
        else ("other", _skeleton(item))
        for item in variant
    ]
    mapping: dict[int, int] = {}
    mapped_variant: set[int] = set()
    matcher = SequenceMatcher(a=base_signatures, b=variant_signatures, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                mapping[i1 + offset] = j1 + offset
                mapped_variant.add(j1 + offset)
        elif tag == "replace" and (i2 - i1) == (j2 - j1):
            for offset in range(i2 - i1):
                left = base[i1 + offset]
                right = variant[j1 + offset]
                if (
                    isinstance(left, dict)
                    and isinstance(right, dict)
                    and left.get("code") == right.get("code")
                    and left.get("indent") == right.get("indent")
                ):
                    mapping[i1 + offset] = j1 + offset
                    mapped_variant.add(j1 + offset)
    return mapping, [index for index in range(len(variant)) if index not in mapped_variant]


class _Merger:
    def __init__(self):
        self.issues: list[SemanticIssue] = []

    def issue(self, path: tuple[Any, ...], kind: str, reason: str, count: int = 1):
        if count > 0:
            self.issues.append(SemanticIssue(_path_text(path), kind, reason, count))

    def merge(self, old: Any, current: Any, new: Any, path: tuple[Any, ...] = ()) -> Any:
        if old is _MISSING or current is _MISSING or new is _MISSING:
            return self._merge_missing(old, current, new, path)

        if isinstance(old, dict) and isinstance(current, dict) and isinstance(new, dict):
            return self._merge_dict(old, current, new, path)
        if isinstance(old, list) and isinstance(current, list) and isinstance(new, list):
            return self._merge_list(old, current, new, path)
        return self._merge_scalar(old, current, new, path)

    def _merge_missing(self, old: Any, current: Any, new: Any, path: tuple[Any, ...]) -> Any:
        if old is _MISSING:
            if current is _MISSING:
                count = _count_japanese(new)
                self.issue(path, "needs_translation", "new upstream source", count)
                return new
            if new is _MISSING:
                self.issue(path, "translator_added", "translator-added structured value")
                return current
            if current == new:
                return new
            self.issue(path, "conflict", "translator-added value collides with new upstream value")
            return new
        if new is _MISSING:
            if current == old or current is _MISSING:
                return _MISSING
            self.issue(path, "conflict", "upstream deleted a translator-modified value")
            return _MISSING
        if current is _MISSING:
            if new == old:
                self.issue(path, "translator_added", "translator removed a structured value")
                return _MISSING
            self.issue(path, "conflict", "translator removed a value changed upstream")
            return new
        raise AssertionError("unreachable missing-value combination")

    def _merge_scalar(self, old: Any, current: Any, new: Any, path: tuple[Any, ...]) -> Any:
        if current == old:
            if new != old and _has_japanese(new):
                self.issue(path, "needs_translation", "source text changed upstream")
            return new
        if new == old:
            if isinstance(old, str) and isinstance(current, str):
                self.issue(path, "preserved_translation", "source text is unchanged")
            return current
        if current == new:
            return new
        if isinstance(old, str) and isinstance(current, str) and isinstance(new, str):
            if _has_japanese(old) or _has_japanese(new):
                self.issue(path, "needs_translation", "translated source text changed upstream")
                return new
        self.issue(path, "conflict", "both translator and upstream changed this value")
        return new

    def _merge_dict(
        self,
        old: dict[str, Any],
        current: dict[str, Any],
        new: dict[str, Any],
        path: tuple[Any, ...],
    ) -> dict[str, Any]:
        output: dict[str, Any] = {}
        keys = (set(old) | set(current) | set(new)) - {"_original"}
        ordered = list(new.keys()) + [key for key in current if key not in new]
        for key in ordered:
            if key == "_original" or key not in keys:
                continue
            merged = self.merge(
                old.get(key, _MISSING),
                current.get(key, _MISSING),
                new.get(key, _MISSING),
                path + (key,),
            )
            if merged is not _MISSING:
                output[key] = merged
        for key in sorted(keys - set(ordered)):
            merged = self.merge(
                old.get(key, _MISSING),
                current.get(key, _MISSING),
                new.get(key, _MISSING),
                path + (key,),
            )
            if merged is not _MISSING:
                output[key] = merged

        original = self._updated_original(old, current, new)
        if original is not _MISSING:
            output["_original"] = original
        return output

    def _updated_original(
        self,
        old: dict[str, Any],
        current: dict[str, Any],
        new: dict[str, Any],
    ) -> Any:
        if "_original" not in current:
            return _MISSING
        metadata = current.get("_original")
        if new == old:
            return metadata
        if isinstance(metadata, dict):
            refreshed: dict[str, Any] = {}
            for key, value in metadata.items():
                if key not in new:
                    continue
                if key in old and new.get(key) == old.get(key):
                    refreshed[key] = value
                elif isinstance(new.get(key), (str, int, float, bool)):
                    refreshed[key] = new[key]
            return refreshed if refreshed else _MISSING

        old_source = self._event_original_source(old)
        new_source = self._event_original_source(new)
        if new_source is not _MISSING:
            return metadata if new_source == old_source else new_source
        return _MISSING

    @staticmethod
    def _event_original_source(command: dict[str, Any]) -> Any:
        code = command.get("code")
        parameters = command.get("parameters")
        if not isinstance(parameters, list):
            return _MISSING
        if code in {401, 405, 408} and parameters:
            return parameters[0]
        if code == 101:
            if len(parameters) > 4:
                return parameters[4]
            if 0 < len(parameters) < 4:
                return parameters[0]
        if code == 102 and parameters and isinstance(parameters[0], list):
            return parameters[0]
        if code == 122 and len(parameters) > 4 and isinstance(parameters[4], str):
            matched = re.search(r"['\"`](.*)['\"`]", parameters[4])
            if matched:
                return matched.group(1)
        return _MISSING

    def _merge_list(
        self, old: list[Any], current: list[Any], new: list[Any], path: tuple[Any, ...]
    ) -> list[Any]:
        if _is_id_list(old) and _is_id_list(current) and _is_id_list(new):
            return self._merge_id_list(old, current, new, path)
        if _is_command_list(old) and _is_command_list(current) and _is_command_list(new):
            return self._merge_command_list(old, current, new, path)
        output: list[Any] = []
        for index in range(max(len(old), len(current), len(new))):
            merged = self.merge(
                old[index] if index < len(old) else _MISSING,
                current[index] if index < len(current) else _MISSING,
                new[index] if index < len(new) else _MISSING,
                path + (index,),
            )
            if merged is not _MISSING:
                output.append(merged)
        return output

    def _merge_id_list(
        self, old: list[Any], current: list[Any], new: list[Any], path: tuple[Any, ...]
    ) -> list[Any]:
        old_by_id = {item["id"]: item for item in old if isinstance(item, dict)}
        current_by_id = {item["id"]: item for item in current if isinstance(item, dict)}
        new_by_id = {item["id"]: item for item in new if isinstance(item, dict)}
        output: list[Any] = [None] if new and new[0] is None else []
        seen: set[Any] = set()
        for item in new:
            if not isinstance(item, dict):
                continue
            item_id = item["id"]
            seen.add(item_id)
            merged = self.merge(
                old_by_id.get(item_id, _MISSING),
                current_by_id.get(item_id, _MISSING),
                item,
                path + (f"id={item_id}",),
            )
            if merged is not _MISSING:
                output.append(merged)
        for item in current:
            if not isinstance(item, dict) or item["id"] in seen:
                continue
            item_id = item["id"]
            merged = self.merge(
                old_by_id.get(item_id, _MISSING), item, _MISSING, path + (f"id={item_id}",)
            )
            if merged is not _MISSING:
                output.append(merged)
        return output

    def _merge_command_list(
        self, old: list[Any], current: list[Any], new: list[Any], path: tuple[Any, ...]
    ) -> list[Any]:
        old_to_current, _current_unmatched = _align_commands(old, current)
        old_to_new, _new_unmatched = _align_commands(old, new, include_source=True)
        (
            old_units,
            current_units,
            old_units_to_current,
            current_units_unmatched,
        ) = _align_command_units(old, current, translated_variant=True)
        (
            _old_units_again,
            new_units,
            old_units_to_new,
            _new_units_unmatched,
        ) = _align_command_units(old, new, translated_variant=False)

        # Logical-unit alignment also disambiguates repeated commands (especially
        # code 101 name-window commands) around collapsed text blocks.
        for old_unit_index, current_unit_index in old_units_to_current.items():
            old_unit = old_units[old_unit_index]
            current_unit = current_units[current_unit_index]
            if (
                old_unit.stop - old_unit.start == 1
                and current_unit.stop - current_unit.start == 1
            ):
                old_to_current[old_unit.start] = current_unit.start
        for old_unit_index, new_unit_index in old_units_to_new.items():
            old_unit = old_units[old_unit_index]
            new_unit = new_units[new_unit_index]
            if (
                old_unit.stop - old_unit.start == 1
                and new_unit.stop - new_unit.start == 1
            ):
                old_to_new[old_unit.start] = new_unit.start
        new_to_old = {new_index: old_index for old_index, new_index in old_to_new.items()}

        # Dazed's translator can shrink 401/408 runs or grow 405 runs while
        # storing the whole joined source in the anchor's _original metadata.
        # Treat every recognized rewrite as one logical replacement. Merging
        # command by command can otherwise restore source continuations or drop
        # translated lines solely because the physical command count changed.
        replacement_by_new_start: dict[int, list[Any]] = {}
        covered_new_indices: set[int] = set()
        for old_unit_index, current_unit_index in old_units_to_current.items():
            old_unit = old_units[old_unit_index]
            current_unit = current_units[current_unit_index]
            if (
                not old_unit.is_text
                or not current_unit.is_text
                or old_unit.stop - old_unit.start
                == current_unit.stop - current_unit.start
            ):
                continue
            old_source = _text_unit_source(old, old_unit, prefer_original=False)
            current_source = _text_unit_source(
                current, current_unit, prefer_original=True
            )
            if not old_source or current_source != old_source:
                continue
            new_unit_index = old_units_to_new.get(old_unit_index)
            if new_unit_index is None:
                continue
            new_unit = new_units[new_unit_index]
            if not _compatible_command_units(old_unit, new_unit):
                continue
            new_source = _text_unit_source(new, new_unit, prefer_original=False)
            covered_new_indices.update(range(new_unit.start, new_unit.stop))
            if new_source == old_source:
                replacement_by_new_start[new_unit.start] = list(
                    current[current_unit.start : current_unit.stop]
                )
                self.issue(
                    path + (new_unit.start,),
                    "preserved_translation",
                    "source text block is unchanged",
                    old_unit.stop - old_unit.start,
                )
            else:
                replacement_by_new_start[new_unit.start] = list(
                    new[new_unit.start : new_unit.stop]
                )
                self.issue(
                    path + (new_unit.start,),
                    "needs_translation",
                    "translated source text block changed upstream",
                    _count_japanese(new[new_unit.start : new_unit.stop]),
                )

        # Script translation may rewrap a code-355 block by inserting code-655
        # continuations. Preserve that whole generated block when upstream did
        # not touch it. If both sides changed the script, prefer the new source
        # in the proposal and keep the file in the review queue.
        for old_unit_index, current_unit_index in old_units_to_current.items():
            old_unit = old_units[old_unit_index]
            current_unit = current_units[current_unit_index]
            if not old_unit.is_script or not current_unit.is_script:
                continue
            new_unit_index = old_units_to_new.get(old_unit_index)
            if new_unit_index is None:
                continue
            new_unit = new_units[new_unit_index]
            if not new_unit.is_script:
                continue
            old_block = old[old_unit.start : old_unit.stop]
            current_block = current[current_unit.start : current_unit.stop]
            new_block = new[new_unit.start : new_unit.stop]
            if current_block == old_block:
                continue
            covered_new_indices.update(range(new_unit.start, new_unit.stop))
            if new_block == old_block:
                replacement_by_new_start[new_unit.start] = list(current_block)
                self.issue(
                    path + (new_unit.start,),
                    "preserved_translation",
                    "source script block is unchanged",
                    _count_japanese(old_block),
                )
            else:
                replacement_by_new_start[new_unit.start] = list(new_block)
                self.issue(
                    path + (new_unit.start,),
                    "conflict",
                    "translator and upstream both changed a script block",
                )
                self.issue(
                    path + (new_unit.start,),
                    "needs_translation",
                    "translated source script block changed upstream",
                    _count_japanese(new_block),
                )

        if current_units_unmatched:
            self.issue(
                path,
                "conflict",
                "translator changed event-command structure; manual file review is required",
            )

        output: list[Any] = []
        for new_index, new_command in enumerate(new):
            if new_index in replacement_by_new_start:
                output.extend(replacement_by_new_start[new_index])
                continue
            if new_index in covered_new_indices:
                continue
            old_index = new_to_old.get(new_index)
            if old_index is None:
                output.append(new_command)
                count = _count_japanese(new_command)
                self.issue(
                    path + (new_index,),
                    "needs_translation",
                    "new upstream event command",
                    count,
                )
                continue
            current_index = old_to_current.get(old_index)
            if current_index is None:
                self.issue(
                    path + (new_index,),
                    "conflict",
                    "an upstream command matches a command removed by the translator",
                )
                output.append(new_command)
                continue
            output.append(
                self.merge(
                    old[old_index],
                    current[current_index],
                    new_command,
                    path + (new_index,),
                )
            )
        self._refresh_text_group_originals(output, new)
        return output

    @staticmethod
    def _refresh_text_group_originals(output: list[Any], new: list[Any]) -> None:
        """Keep anchor ``_original`` synchronized for multi-line text groups.

        The translator stores the joined source on the first 401/405/408 command.
        Updating only a later line must therefore refresh the anchor as a group.
        """
        output_units = _command_units(output)
        new_units = _command_units(new)
        if len(output_units) != len(new_units):
            return
        for output_unit, new_unit in zip(output_units, new_units):
            if (
                not output_unit.is_text
                or not new_unit.is_text
                or not _compatible_command_units(output_unit, new_unit)
            ):
                continue
            new_source = _text_unit_source(new, new_unit, prefer_original=False)
            visible = _text_unit_source(output, output_unit, prefer_original=False)
            metadata_present = any(
                isinstance(output[index], dict) and "_original" in output[index]
                for index in range(output_unit.start, output_unit.stop)
            )
            if new_source and (metadata_present or visible != new_source):
                output_command = output[output_unit.start]
                if not isinstance(output_command, dict):
                    continue
                output_command["_original"] = new_source
                for index in range(output_unit.start + 1, output_unit.stop):
                    extra = output[index]
                    if isinstance(extra, dict):
                        extra.pop("_original", None)


class _PluginMerger(_Merger):
    """Merge RPG Maker plugin settings, including JSON stored inside strings."""

    @staticmethod
    def _embedded_json(value: Any) -> Any:
        if not isinstance(value, str) or not value.lstrip().startswith(("{", "[")):
            return _MISSING
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return _MISSING
        return parsed if isinstance(parsed, (dict, list)) else _MISSING

    def _merge_scalar(
        self, old: Any, current: Any, new: Any, path: tuple[Any, ...]
    ) -> Any:
        embedded = tuple(self._embedded_json(value) for value in (old, current, new))
        if all(value is not _MISSING for value in embedded):
            merged = self.merge(*embedded, path + ("embedded JSON",))
            return json.dumps(merged, ensure_ascii=False, separators=(",", ":"))
        return super()._merge_scalar(old, current, new, path)


_PLUGINS_ASSIGNMENT = re.compile(r"\bvar\s+\$plugins\s*=", re.MULTILINE)


def _decode_plugins_js(data: bytes) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"plugins.js is not UTF-8: {exc}") from exc
    match = _PLUGINS_ASSIGNMENT.search(text)
    if match is None:
        raise ValueError("plugins.js does not contain 'var $plugins ='")
    payload = text[match.end() :].strip()
    if payload.endswith(";"):
        payload = payload[:-1].rstrip()
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"plugins.js plugin array could not be decoded: {exc}") from exc
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("plugins.js must contain an array of plugin objects")
    names = [item.get("name") for item in value]
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError("every plugins.js entry must have a non-empty name")
    if len(names) != len(set(names)):
        raise ValueError("plugins.js contains duplicate plugin names")
    return value


def merge_plugins_js_bytes(
    old: bytes, current: bytes, new: bytes
) -> SemanticMergeResult:
    """Merge the generated plugin registry by plugin name, preserving new order."""
    old_plugins = _decode_plugins_js(old)
    current_plugins = _decode_plugins_js(current)
    new_plugins = _decode_plugins_js(new)
    old_by_name = {item["name"]: item for item in old_plugins}
    current_by_name = {item["name"]: item for item in current_plugins}
    new_names = {item["name"] for item in new_plugins}
    merger = _PluginMerger()
    output: list[dict[str, Any]] = []

    for plugin in new_plugins:
        name = plugin["name"]
        merged = merger.merge(
            old_by_name.get(name, _MISSING),
            current_by_name.get(name, _MISSING),
            plugin,
            (f"plugin={name}",),
        )
        if merged is not _MISSING:
            output.append(merged)

    # Keep genuinely translator-added plugins, but honor upstream deletion of
    # plugins that existed in the old official version.
    for plugin in current_plugins:
        name = plugin["name"]
        if name in new_names:
            continue
        merged = merger.merge(
            old_by_name.get(name, _MISSING),
            plugin,
            _MISSING,
            (f"plugin={name}",),
        )
        if merged is not _MISSING:
            output.append(merged)

    content = (
        "// Generated by RPG Maker.\n"
        "// Do not edit this file directly.\n"
        "var $plugins = "
        + json.dumps(output, ensure_ascii=False, indent=2)
        + ";\n"
    ).encode("utf-8")
    return SemanticMergeResult(content=content, issues=merger.issues)


def merge_json_bytes(old: bytes, current: bytes, new: bytes) -> SemanticMergeResult:
    try:
        old_data = json.loads(old.decode("utf-8-sig"))
        current_data = json.loads(current.decode("utf-8-sig"))
        new_data = json.loads(new.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"RPG Maker JSON could not be decoded: {exc}") from exc

    merger = _Merger()
    output = merger.merge(old_data, current_data, new_data)
    content = (json.dumps(output, ensure_ascii=False, indent=4) + "\n").encode("utf-8")
    return SemanticMergeResult(content=content, issues=merger.issues)


def count_japanese_source_bytes(data: bytes) -> int:
    """Count Japanese string values in a newly introduced RPG Maker JSON file."""
    try:
        value = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 0
    return _count_japanese(value)


def count_changed_japanese_source_bytes(old: bytes, new: bytes) -> int:
    """Count Japanese string values whose source value is new or changed."""
    try:
        old_value = json.loads(old.decode("utf-8-sig"))
        new_value = json.loads(new.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 0

    def count(left: Any, right: Any) -> int:
        if isinstance(left, dict) and isinstance(right, dict):
            return sum(count(left.get(key, _MISSING), value) for key, value in right.items())
        if isinstance(left, list) and isinstance(right, list):
            return sum(
                count(left[index] if index < len(left) else _MISSING, value)
                for index, value in enumerate(right)
            )
        if left != right:
            return _count_japanese(right)
        return 0

    return count(old_value, new_value)


def count_preserved_translation_bytes(old: bytes, current: bytes) -> int:
    """Count Japanese source strings replaced by a visible translated value."""
    try:
        old_value = json.loads(old.decode("utf-8-sig"))
        current_value = json.loads(current.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 0

    def count(left: Any, right: Any) -> int:
        if isinstance(left, dict) and isinstance(right, dict):
            return sum(
                count(value, right.get(key, _MISSING))
                for key, value in left.items()
                if key != "_original"
            )
        if isinstance(left, list) and isinstance(right, list):
            return sum(
                count(value, right[index] if index < len(right) else _MISSING)
                for index, value in enumerate(left)
            )
        return int(_has_japanese(left) and right is not _MISSING and left != right)

    return count(old_value, current_value)
