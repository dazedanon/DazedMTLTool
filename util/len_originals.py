"""Preserve Workflow-compatible source metadata before Len writes MV/MZ JSON.

The input must be a matching untranslated baseline, or the previous game document
with its originals intact. This deliberately refuses topology changes: adapters
that insert/reorder commands must carry explicit source bindings themselves.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re

from util.rpgmaker_qa_manifest import SCALAR_PARAMETER

_FIELDS = {
    "name", "nickname", "profile", "description", "note", "displayName",
    "message1", "message2", "message3", "message4", "gameTitle", "currencyUnit",
}
_SYSTEM_FIELDS = _FIELDS | {
    "terms", "armorTypes", "skillTypes", "equipTypes", "elements", "weaponTypes",
    "switches", "variables", "locale",
}
_RUNS = {401: 401, 405: 405, 108: 408, 408: 408, 355: 655}


def _merge(kept, added):
    """Fill absent leaves, retaining every previously recorded source."""
    if added is None:
        return copy.deepcopy(kept)
    if kept is None or (isinstance(kept, str) and not kept.strip()):
        return copy.deepcopy(added)
    if isinstance(kept, dict) and isinstance(added, dict):
        result = copy.deepcopy(kept)
        for key, value in added.items():
            result[key] = _merge(result.get(key), value)
        return result
    if isinstance(kept, list) and isinstance(added, list) and len(kept) == len(added):
        return [_merge(a, b) for a, b in zip(kept, added)]
    if isinstance(kept, str) and isinstance(added, str):
        return kept
    raise ValueError("Incompatible _original shape; use an adapter with explicit source bindings.")


def _changed(before, after):
    if isinstance(before, str):
        return before if before.strip() and before != after else None
    if not isinstance(before, (list, dict)):
        return None
    items = enumerate(before) if isinstance(before, list) else before.items()
    result = {}
    for key, value in items:
        if key == "_original":
            continue
        if isinstance(value, (str, dict, list)):
            changed = _changed(value, after[key])
            if changed is not None:
                result[str(key)] = changed
    return result or None


def _align(before, after, path=""):
    """Check positional bindings before attaching any source to a live field."""
    if type(before) is not type(after):
        raise ValueError(f"JSON shape changed at {path or '/'}; explicit source bindings required.")
    if isinstance(before, dict):
        if before.keys() - {"_original"} != after.keys() - {"_original"}:
            raise ValueError(f"JSON fields changed at {path or '/'}; explicit source bindings required.")
        for key in before.keys() - {"_original"}:
            if key in {"id", "code", "indent"} and before[key] != after[key]:
                raise ValueError(f"JSON identity changed at {path}/{key}.")
            _align(before[key], after[key], f"{path}/{key}")
    elif isinstance(before, list):
        if len(before) != len(after):
            raise ValueError(f"JSON array length changed at {path or '/'}; explicit source bindings required.")
        for index, (old, new) in enumerate(zip(before, after)):
            _align(old, new, f"{path}/{index}")


def _inherit(before, after):
    """Restore missing metadata and reject edits to authoritative originals."""
    if isinstance(before, dict):
        if "_original" in after and after["_original"] != before.get("_original"):
            raise ValueError("Staged _original differs from the trusted source. Keep source metadata unchanged.")
        if "_original" in before:
            after["_original"] = copy.deepcopy(before["_original"])
        for key in before.keys() - {"_original"}:
            _inherit(before[key], after[key])
    elif isinstance(before, list):
        for old, new in zip(before, after):
            _inherit(old, new)


def _remember(owner, original):
    if original is not None:
        owner["_original"] = _merge(owner.get("_original"), original)


def _command(before, after):
    code = before["code"]
    old, new = before["parameters"], after["parameters"]
    if old == new:
        return
    if code == 101:
        index = 4 if len(old) > 4 else 0 if 0 < len(old) < 4 else None
        if index is not None:
            _remember(after, _changed(old[index], new[index]))
    elif code == 102:
        choices = [_changed(a, b) for a, b in zip(old[0], new[0])]
        if any(value is not None for value in choices):
            _remember(after, choices)
    elif code == 122:
        if old[4] != new[4] and isinstance(old[4], str):
            # QA maps legacy code-122 originals to the quoted inner string.
            pattern = r"\s*(['\"`])((?:\\[^\r\n]|(?!\1)[^\\\r\n])*)\1\s*"
            source = re.fullmatch(pattern, old[4])
            live = re.fullmatch(pattern, new[4])
            if not source or not live:
                raise ValueError("Code 122 requires a single quoted literal; use an explicit source adapter.")
            _remember(after, _changed(source.group(2), live.group(2)))
    elif code in SCALAR_PARAMETER or code in {401, 405}:
        index = SCALAR_PARAMETER.get(code, 0)
        _remember(after, _changed(old[index], new[index]))
    elif code in {111, 357}:
        changed = _changed(old, new)
        if changed:
            existing = after.get("_original")
            if code == 357 and isinstance(existing, dict) and "parameters" not in existing:
                # Preserve the legacy argument-keyed representation.
                if changed.keys() - {"3"}:
                    raise ValueError("Legacy code 357 originals only bind argument fields.")
                _remember(after, changed["3"])
            else:
                _remember(after, {"parameters": changed})
    elif code != 402 and _changed(old, new):
        raise ValueError(f"Unsupported translated event code {code}; use an explicit source adapter.")
    # 402 labels mirror the choices already preserved on 102.


def _walk(before, after, *, system=False):
    if isinstance(before, list):
        index = 0
        while index < len(before):
            item = before[index]
            code = item.get("code") if isinstance(item, dict) else None
            if code in _RUNS:
                end = index + 1
                while end < len(before):
                    following = before[end]
                    if (not isinstance(following, dict) or following.get("code") != _RUNS[code]
                            or "_original" in following):
                        break
                    end += 1
                old = [row["parameters"][0] for row in before[index:end]]
                new = [row["parameters"][0] for row in after[index:end]]
                if old != new:
                    original = "\n".join(old)
                    _remember(after[index], original if original.strip() else None)
                index = end
            else:
                _walk(item, after[index])
                index += 1
    elif isinstance(before, dict):
        if "code" in before and "parameters" in before:
            _command(before, after)
            return
        for key, value in before.items():
            if key == "_original":
                continue
            if key in (_SYSTEM_FIELDS if system else _FIELDS):
                changed = _changed(value, after[key]) if isinstance(value, (str, list, dict)) else None
                if changed is not None:
                    _remember(after, {key: changed})
            elif isinstance(value, (list, dict)):
                _walk(value, after[key])
            elif isinstance(value, str) and value != after[key]:
                raise ValueError(f"Unsupported translated field {key!r}; use an explicit source adapter.")
    elif isinstance(before, str) and before != after:
        raise ValueError("Unsupported translated string array; use an explicit source adapter.")


def preserve_originals(source, translated, *, filename: str):
    """Return an annotated copy; neither input is mutated, even on refusal.

    Only use with MV/MZ data JSON whose array ordering has been retained. Numbers
    may change for layout, but IDs, command codes/indents and all shapes must match.
    Existing grouped-source boundaries remain authoritative during corrections.
    """
    _align(source, translated)
    result = copy.deepcopy(translated)
    _inherit(source, result)
    if filename == "System.json" and isinstance(result, dict) and "locale" in result:
        result["locale"] = "en_US"
    _walk(source, result, system=filename == "System.json")
    return result


def write_rpgmaker_json(source: Path, translated: Path, output: Path) -> Path:
    """Validate staged text and atomically write one file with preserved sources."""
    from util.len_translation import _write_atomic

    if output.suffix.lower() != ".json":
        raise ValueError("This writer supports MV/MZ data JSON only; native/binary formats need source sidecars.")
    if translated.resolve() in {source.resolve(), output.resolve()}:
        raise ValueError("Use a separate staged translation file; source and output may be the same game file.")
    if output.is_symlink():
        raise ValueError(f"Refusing to replace a symlink: {output}")
    previous_bytes = output.read_bytes() if output.exists() else None
    source_doc = json.loads(source.read_bytes().decode("utf-8-sig"))
    staged_bytes = translated.read_bytes()
    staged_doc = json.loads(staged_bytes.decode("utf-8-sig"))
    if previous_bytes is not None:
        previous = json.loads(previous_bytes.decode("utf-8-sig"))
        _align(previous, source_doc)
        # Existing game metadata is authoritative, including when staging starts
        # from a clean Japanese baseline rather than the previous translated file.
        _inherit(previous, source_doc)
    result = preserve_originals(source_doc, staged_doc, filename=output.name)
    text = staged_bytes.decode("utf-8-sig")
    indentation = re.search(r"\n([ \t]+)\"", text)
    indent = indentation.group(1) if indentation else None
    rendered = json.dumps(result, ensure_ascii=False, indent=indent,
                          separators=None if indent else (",", ":"))
    if "\r\n" in text:
        rendered = rendered.replace("\n", "\r\n")
    if text.endswith("\n"):
        rendered += "\r\n" if text.endswith("\r\n") else "\n"
    if staged_bytes.startswith(b"\xef\xbb\xbf"):
        rendered = "\ufeff" + rendered
    if (output.read_bytes() if output.exists() else None) != previous_bytes:
        raise ValueError("Output changed while preparing the write; rerun against the current game file.")
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(output, rendered)
    return output
