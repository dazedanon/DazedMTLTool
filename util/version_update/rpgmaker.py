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
    if code == 101 and len(parameters) > 4:
        return parameters[4]
    if code == 102 and parameters:
        return parameters[0]
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
        if code == 101 and len(parameters) > 4:
            return parameters[4]
        if code == 102 and parameters and isinstance(parameters[0], list):
            return parameters[0]
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
        old_to_current, current_unmatched = _align_commands(old, current)
        old_to_new, _new_unmatched = _align_commands(old, new, include_source=True)
        new_to_old = {new_index: old_index for old_index, new_index in old_to_new.items()}
        if current_unmatched:
            self.issue(
                path,
                "conflict",
                "translator changed event-command structure; manual file review is required",
            )

        output: list[Any] = []
        for new_index, new_command in enumerate(new):
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
        index = 0
        while index < min(len(output), len(new)):
            output_command = output[index]
            new_command = new[index]
            if not isinstance(output_command, dict) or not isinstance(new_command, dict):
                index += 1
                continue
            code = new_command.get("code")
            if code not in {401, 405, 408}:
                index += 1
                continue
            end = index
            new_parts: list[str] = []
            visible_parts: list[str] = []
            metadata_present = False
            while end < min(len(output), len(new)):
                out_item = output[end]
                new_item = new[end]
                if (
                    not isinstance(out_item, dict)
                    or not isinstance(new_item, dict)
                    or new_item.get("code") != code
                ):
                    break
                out_params = out_item.get("parameters") or []
                new_params = new_item.get("parameters") or []
                if out_params:
                    visible_parts.append(str(out_params[0]))
                if new_params:
                    new_parts.append(str(new_params[0]))
                metadata_present = metadata_present or "_original" in out_item
                end += 1
            new_source = "\n".join(new_parts)
            visible = "\n".join(visible_parts)
            if new_source and (metadata_present or visible != new_source):
                output_command["_original"] = new_source
                for extra in output[index + 1 : end]:
                    if isinstance(extra, dict):
                        extra.pop("_original", None)
            index = max(index + 1, end)


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
