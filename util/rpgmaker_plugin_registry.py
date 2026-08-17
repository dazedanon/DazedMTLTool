"""Safe edits for RPG Maker MV/MZ ``plugins.js`` registries."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

import jsbeautifier


class PluginRegistryError(ValueError):
    """Raised when plugins.js cannot be edited without risking corruption."""


@dataclass(frozen=True)
class _RegistryEntry:
    value: dict
    raw: str


@dataclass(frozen=True)
class _Registry:
    array_start: int
    array_end: int
    entries: tuple[_RegistryEntry, ...]
    item_indent: str
    closing_indent: str


def _assignment_array_start(content: str) -> int:
    match = re.search(r"\bvar\s+\$plugins\s*=\s*", content)
    if match is None:
        raise PluginRegistryError("plugins.js has no 'var $plugins =' assignment")
    position = match.end()
    while position < len(content) and content[position].isspace():
        position += 1
    if position >= len(content) or content[position] != "[":
        raise PluginRegistryError("the $plugins assignment is not an array")
    return position


def _indent_before(content: str, position: int) -> str:
    line_start = max(content.rfind("\n", 0, position), content.rfind("\r", 0, position))
    indent = content[line_start + 1 : position]
    return indent if not indent.strip() else ""


def _parse_registry(content: str) -> _Registry:
    array_start = _assignment_array_start(content)
    decoder = json.JSONDecoder()
    try:
        values, array_end = decoder.raw_decode(content, array_start)
    except json.JSONDecodeError as exc:
        raise PluginRegistryError(
            f"invalid $plugins array at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(values, list):
        raise PluginRegistryError("the $plugins assignment is not an array")

    trailer = content[array_end:].lstrip()
    if not trailer.startswith(";"):
        raise PluginRegistryError("the $plugins array is not followed by a semicolon")

    entries: list[_RegistryEntry] = []
    position = array_start + 1
    while True:
        while position < array_end and content[position].isspace():
            position += 1
        if position >= array_end or content[position] == "]":
            break
        try:
            value, entry_end = decoder.raw_decode(content, position)
        except json.JSONDecodeError as exc:
            raise PluginRegistryError(
                f"invalid plugin entry at line {exc.lineno}, column {exc.colno}: {exc.msg}"
            ) from exc
        if not isinstance(value, dict):
            raise PluginRegistryError("every $plugins array entry must be an object")
        entries.append(_RegistryEntry(value=value, raw=content[position:entry_end]))
        position = entry_end
        while position < array_end and content[position].isspace():
            position += 1
        if position < array_end and content[position] == ",":
            position += 1
            continue
        if position >= array_end or content[position] != "]":
            raise PluginRegistryError("plugin entries must be separated by one comma")

    if len(entries) != len(values):
        raise PluginRegistryError("could not account for every plugin registry entry")
    if entries:
        first_entry = content.find(entries[0].raw, array_start + 1, array_end)
        item_indent = _indent_before(content, first_entry)
    else:
        item_indent = ""
    closing_indent = _indent_before(content, array_end - 1)
    if not item_indent:
        item_indent = closing_indent + "    "
    return _Registry(
        array_start=array_start,
        array_end=array_end,
        entries=tuple(entries),
        item_indent=item_indent,
        closing_indent=closing_indent,
    )


def _repair_legacy_leading_comma(content: str) -> str:
    """Remove the bad token emitted by the former empty-list installer."""
    array_start = _assignment_array_start(content)
    position = array_start + 1
    while position < len(content) and content[position].isspace():
        position += 1
    if position < len(content) and content[position] == ",":
        repaired = content[:position] + content[position + 1 :]
        _parse_registry(repaired)
        return repaired
    return content


def _render_registry(
    content: str,
    registry: _Registry,
    entries: list[str],
    newline: str,
) -> str:
    if entries:
        rendered = newline + ("," + newline).join(
            registry.item_indent + entry.strip() for entry in entries
        )
        rendered += newline + registry.closing_indent
    else:
        rendered = newline + registry.closing_indent
    return (
        content[: registry.array_start + 1]
        + rendered
        + content[registry.array_end - 1 :]
    )


def _matches_remnant(
    value: dict,
    plugin_name: str,
    description_prefixes: tuple[str, ...],
) -> bool:
    if value.get("name") == plugin_name:
        return True
    description = value.get("description")
    return (
        not value.get("name")
        and isinstance(description, str)
        and description.startswith(description_prefixes)
    )


def update_plugin_entry(
    content: str,
    plugin_name: str,
    entry: str | None,
    newline: str,
    *,
    description_prefixes: tuple[str, ...] = (),
) -> str:
    """Return a valid registry with zero or one canonical target entry.

    ``entry`` adds/replaces the plugin; ``None`` removes it. A leading comma
    produced by older DazedTL installers is repaired before the edit.
    """
    repaired = _repair_legacy_leading_comma(content)
    registry = _parse_registry(repaired)
    retained = [
        item.raw
        for item in registry.entries
        if not _matches_remnant(item.value, plugin_name, description_prefixes)
    ]
    if entry is not None:
        try:
            entry_value = json.loads(entry)
        except json.JSONDecodeError as exc:
            raise PluginRegistryError(f"generated {plugin_name} entry is invalid") from exc
        if not isinstance(entry_value, dict) or entry_value.get("name") != plugin_name:
            raise PluginRegistryError(
                f"generated plugin entry does not declare {plugin_name}"
            )
        retained.append(entry.strip())

    proposed = format_plugins_js(
        _render_registry(repaired, registry, retained, newline)
    )
    validated = _parse_registry(proposed)
    if any(not isinstance(item.value.get("name"), str) for item in validated.entries):
        raise PluginRegistryError("every plugin registry entry must have a string name")
    count = sum(item.value.get("name") == plugin_name for item in validated.entries)
    expected = 1 if entry is not None else 0
    if count != expected:
        raise PluginRegistryError(
            f"plugins.js would contain {count} {plugin_name} entries instead of {expected}"
        )
    return proposed


def format_plugins_js(content: str) -> str:
    """Apply the same canonical layout as the workflow formatter."""
    options = jsbeautifier.default_options()
    options.indent_size = 2
    options.indent_char = " "
    options.max_preserve_newlines = 2
    options.preserve_newlines = True
    options.end_with_newline = True
    return jsbeautifier.beautify(content, options)


def plugin_names(content: str) -> tuple[str, ...]:
    """Validate a registry and return its plugin names in load order."""
    registry = _parse_registry(content)
    if any(not isinstance(item.value.get("name"), str) for item in registry.entries):
        raise PluginRegistryError("every plugin registry entry must have a string name")
    return tuple(item.value["name"] for item in registry.entries)


def _atomic_write_bytes(path: Path, payload: bytes, mode: int | None = None) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise OSError(f"refusing to replace non-regular file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.dazedtl-", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, content: str) -> None:
    """Atomically replace a regular UTF-8 text file."""
    _atomic_write_bytes(path, content.encode("utf-8"))


def install_plugin_files(
    target: Path,
    plugin_content: str,
    plugins_js: Path,
    registry_content: str,
) -> None:
    """Install a plugin file, rolling it back if the registry write fails."""
    if plugins_js.is_symlink() or not plugins_js.is_file():
        raise OSError(f"plugins.js is not a regular file: {plugins_js}")
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise OSError(f"plugin destination is not a regular file: {target}")

    previous = target.read_bytes() if target.exists() else None
    previous_mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
    atomic_write_text(target, plugin_content)
    try:
        atomic_write_text(plugins_js, registry_content)
    except Exception as exc:
        try:
            if previous is None:
                target.unlink(missing_ok=True)
            else:
                _atomic_write_bytes(target, previous, previous_mode)
        except Exception as rollback_exc:
            raise OSError(
                f"plugins.js was unchanged, but the plugin-file rollback failed: {rollback_exc}"
            ) from exc
        raise
