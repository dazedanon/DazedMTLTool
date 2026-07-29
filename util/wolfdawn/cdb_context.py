"""Resolve ``\\cdb[type:row:field]`` display values for translation context.

WolfDawn's normal strings extraction intentionally contains only translatable
strings.  A runtime CDB lookup can therefore point at a value (most notably an
actor name) that is absent from ``CDataBase.project.json``.  ``wolf db-json``
exposes the complete database, so the workflow stores a small hidden lookup
sidecar and the translation module can show the real value to the model while
still restoring the original control code for injection.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from util import wolfdawn

SIDECAR_NAME = ".cdb-context.json"
SIDECAR_KIND = "wolf-cdb-context"


def lookup_from_db_json(data: dict[str, Any]) -> dict[str, str]:
    """Return ``{"type:row:field": value}`` from a ``wolf db-json`` document."""
    lookups: dict[str, str] = {}
    for type_doc in data.get("types") or []:
        if not isinstance(type_doc, dict):
            continue
        type_id = type_doc.get("id")
        fields = {
            field.get("id"): field.get("name")
            for field in type_doc.get("fields") or []
            if isinstance(field, dict)
        }
        for row in type_doc.get("rows") or []:
            if not isinstance(row, dict):
                continue
            row_id = row.get("id")
            values = row.get("values") or {}
            if not isinstance(values, dict):
                continue
            for field_id, field_name in fields.items():
                if not isinstance(field_name, str):
                    continue
                value = values.get(field_name)
                if isinstance(value, str) and value.strip():
                    lookups[f"{type_id}:{row_id}:{field_id}"] = value
    return lookups


def lookup_from_strings_extract(data: dict[str, Any]) -> dict[str, str]:
    """Best-effort fallback using the ordinary CDataBase extraction."""
    lookups: dict[str, str] = {}
    for group in data.get("groups") or []:
        if not isinstance(group, dict):
            continue
        type_id = group.get("type")
        for line in group.get("lines") or []:
            if not isinstance(line, dict):
                continue
            row_id, field_id = line.get("row"), line.get("field")
            value = line.get("source")
            if isinstance(value, str) and value.strip():
                lookups[f"{type_id}:{row_id}:{field_id}"] = value
    return lookups


def write_sidecar(project_path: str | Path, sidecar_path: str | Path, log_fn=None) -> bool:
    """Dump a complete CDB once, reduce it to display strings, and save a sidecar."""
    project = Path(project_path)
    sidecar = Path(sidecar_path)
    if not project.is_file():
        return False
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="dazedtl-cdb-") as temp_dir:
            full_json = Path(temp_dir) / "CDataBase.full.json"
            result = wolfdawn.db_json(project, full_json, log_fn=log_fn)
            if not result.ok or not full_json.is_file():
                return False
            data = json.loads(full_json.read_text(encoding="utf-8"))
        payload = {
            "kind": SIDECAR_KIND,
            "source": str(project),
            "lookups": lookup_from_db_json(data),
        }
        sidecar.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return True
    except (OSError, ValueError, TypeError):
        return False


def read_sidecar(path: str | Path) -> dict[str, str]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    lookups = data.get("lookups") if isinstance(data, dict) else None
    if not isinstance(lookups, dict):
        return {}
    return {
        str(key): value
        for key, value in lookups.items()
        if isinstance(value, str) and value.strip()
    }


def _source_project(game_root: Path) -> Path | None:
    work_dir = game_root / "wolf_json"
    candidates = (
        work_dir / "originals" / "BasicData" / "CDataBase.project",
        work_dir / "originals" / "CDataBase.project",
        game_root / "Data" / "BasicData" / "CDataBase.project",
        game_root / "data" / "BasicData" / "CDataBase.project",
        game_root / "BasicData" / "CDataBase.project",
    )
    return next((path for path in candidates if path.is_file()), None)


def load_translation_lookup(files_dir: str | Path = "files") -> dict[str, str]:
    """Load CDB context, lazily creating the hidden sidecar for older extracts."""
    lookups: dict[str, str] = {}
    files_path = Path(files_dir)

    # The ordinary extraction is incomplete but provides a useful no-root fallback.
    extracted = files_path / "CDataBase.project.json"
    if extracted.is_file():
        try:
            lookups.update(
                lookup_from_strings_extract(
                    json.loads(extracted.read_text(encoding="utf-8-sig"))
                )
            )
        except (OSError, ValueError, TypeError):
            pass

    root_value = (os.getenv("DAZED_GAME_ROOT") or "").strip()
    if not root_value:
        return lookups
    game_root = Path(root_value)
    sidecar = game_root / "wolf_json" / SIDECAR_NAME
    if not sidecar.is_file():
        source = _source_project(game_root)
        if source is not None:
            write_sidecar(source, sidecar)
    # Complete db-json values take precedence over the strings-only fallback.
    lookups.update(read_sidecar(sidecar))
    return lookups
