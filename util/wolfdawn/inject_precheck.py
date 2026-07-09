"""Pre-inject review: list WolfDawn safety-guard skips before writing binaries.

WolfDawn ``strings-inject`` outcomes:

* ``applied`` - translation written
* ``untranslated`` - ``text == source`` (left alone; not a problem, not listed here)
* ``drifted`` - base no longer holds ``source`` (stale Data/; file-level, not listed here)
* ``control-code mismatch`` / ``text not representable`` - safety skips (listed)

This module dry-runs selected files and resolves safety locators back into editable
JSON lines so Step 6 can show a review list before inject.
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from util.wolfdawn import codes as wolf_codes
from util.wolfdawn import db_dat_sibling
from util import wolfdawn
from util.wolfdawn.inject import NAMES_JSON, orig_base_for, repair_inject_json

_DB_LOC_RE = re.compile(
    r"^db\s+type\s+(?P<type>\d+)\s+row\s+(?P<row>\d+)\s+field\s+(?P<field>\d+)\s*$",
    re.IGNORECASE,
)
_EVENT_LOC_RE = re.compile(
    r"^event\s+(?P<event>\d+)"
    r"(?:\s+page\s+(?P<page>\d+))?"
    r"\s+cmd\s+(?P<cmd>\d+)\s+str\s+(?P<str>\d+)\s*$",
    re.IGNORECASE,
)
_GAMEDAT_LOC_RE = re.compile(r"^gamedat\s+(?P<key>.+)\s*$", re.IGNORECASE)


@dataclass
class InjectIssue:
    """One line skipped by a WolfDawn safety guard."""

    json_file: str
    kind: str  # code_mismatch | unrepresentable
    locator: str
    message: str
    source: str = ""
    text: str = ""
    hit_id: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        label = {
            "code_mismatch": "control-code mismatch",
            "unrepresentable": "not Shift-JIS encodable",
        }.get(self.kind, self.kind)
        preview = (self.text or self.source).replace("\n", " ").strip()
        if len(preview) > 90:
            preview = preview[:90] + "…"
        loc = self.locator or self.json_file
        if preview:
            return f"{label}\n{self.json_file} · {loc}\n{preview}"
        return f"{label}\n{self.json_file} · {loc}"


@dataclass
class FilePrecheck:
    json_name: str
    would_apply: int | None = None
    drifted: int | None = None
    safety_count: int | None = None
    issues: list[InjectIssue] = field(default_factory=list)
    error: str = ""
    detail: str = ""


@dataclass
class PrecheckReport:
    files: list[FilePrecheck] = field(default_factory=list)

    @property
    def issues(self) -> list[InjectIssue]:
        out: list[InjectIssue] = []
        for f in self.files:
            out.extend(f.issues)
        return out

    @property
    def safety_issues(self) -> list[InjectIssue]:
        return list(self.issues)

    @property
    def ok(self) -> bool:
        return all(not f.error for f in self.files)


def _load_doc(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def resolve_locator_line(
    doc: dict[str, Any], locator: str
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Map a WolfDawn inject locator to the JSON line dict and a hit_id."""
    kind = str(doc.get("kind") or "")
    m = _DB_LOC_RE.match(locator.strip())
    if m and kind == "db":
        type_id, row, field = int(m.group("type")), int(m.group("row")), int(m.group("field"))
        for g in doc.get("groups") or []:
            if not isinstance(g, dict) or g.get("type") != type_id:
                continue
            type_name = str(g.get("typeName") or type_id)
            for ln in g.get("lines") or []:
                if not isinstance(ln, dict):
                    continue
                if ln.get("row") == row and ln.get("field") == field:
                    return ln, {
                        "json_file": "",
                        "kind": "db",
                        "sheet_name": type_name,
                        "row": row,
                        "field_name": str(ln.get("fieldName") or ""),
                        "type": type_id,
                        "field": field,
                    }
        return None, {
            "kind": "db",
            "type": type_id,
            "row": row,
            "field": field,
            "sheet_name": str(type_id),
        }

    m = _EVENT_LOC_RE.match(locator.strip())
    if m and kind in ("map", "common"):
        event = int(m.group("event"))
        page = m.group("page")
        page_i = int(page) if page is not None else None
        cmd, si_arg = int(m.group("cmd")), int(m.group("str"))
        for si, sc in enumerate(doc.get("scenes") or []):
            if not isinstance(sc, dict) or sc.get("event") != event:
                continue
            if page_i is not None and sc.get("page") != page_i:
                continue
            for li, ln in enumerate(sc.get("lines") or []):
                if not isinstance(ln, dict):
                    continue
                if ln.get("cmd") == cmd and ln.get("str") == si_arg:
                    return ln, {
                        "json_file": "",
                        "kind": kind,
                        "sheet_name": "",
                        "scene_index": si,
                        "line_index": li,
                        "event": event,
                        "page": page_i,
                        "cmd": cmd,
                        "str": si_arg,
                    }
        return None, {
            "kind": kind,
            "event": event,
            "page": page_i,
            "cmd": cmd,
            "str": si_arg,
        }

    m = _GAMEDAT_LOC_RE.match(locator.strip())
    if m and kind == "gamedat":
        key = m.group("key").strip()
        for ln in doc.get("lines") or []:
            if isinstance(ln, dict) and str(ln.get("key") or "") == key:
                return ln, {
                    "json_file": "",
                    "kind": "gamedat",
                    "sheet_name": "Game.dat",
                    "field_name": key,
                    "key": key,
                }
        return None, {"kind": "gamedat", "key": key, "sheet_name": "Game.dat"}

    return None, {}


def apply_issue_text(
    translated_dir: Path,
    issue: InjectIssue,
    new_text: str,
) -> tuple[bool, str]:
    """Write *new_text* onto the JSON line for *issue*. Returns (ok, error)."""
    path = Path(translated_dir) / issue.json_file
    if not path.is_file():
        return False, f"{issue.json_file} not found"
    doc = _load_doc(path)
    if not doc:
        return False, f"could not read {issue.json_file}"

    line: dict[str, Any] | None = None
    if issue.locator:
        line, _ = resolve_locator_line(doc, issue.locator)
    if line is None and issue.hit_id.get("kind") == "db":
        line, _ = resolve_locator_line(
            doc,
            f"db type {issue.hit_id.get('type')} row {issue.hit_id.get('row')} "
            f"field {issue.hit_id.get('field')}",
        )

    if line is None:
        return False, f"could not locate {issue.locator or issue.json_file}"

    line["text"] = new_text
    src = line.get("source")
    if isinstance(src, str) and isinstance(new_text, str):
        repaired = wolf_codes.rebuild_text_preserving_source_codes(src, new_text)
        if repaired != new_text:
            line["text"] = repaired
    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    issue.text = str(line.get("text") or "")
    return True, ""


def _precheck_strings_file(
    json_name: str,
    entry: dict,
    inject_src: Path,
    data_dir: Path,
    originals_dir: Path,
    *,
    allow_code_drift: bool,
    en_punct: bool,
) -> FilePrecheck:
    result = FilePrecheck(json_name=json_name)
    orig = orig_base_for(entry, data_dir, originals_dir)
    if not orig.exists():
        result.error = f"no pristine original at {orig} (re-run Step 0 extract)"
        return result
    if entry.get("kind") == "db" and not db_dat_sibling(orig).is_file():
        result.error = "missing database .dat pair in originals (re-run Step 0 extract)"
        return result

    doc = _load_doc(inject_src)

    with tempfile.TemporaryDirectory(prefix="wolf-precheck-") as tmp:
        out = Path(tmp) / Path(entry["base"]).name
        res = wolfdawn.strings_inject(
            str(inject_src),
            str(orig),
            str(out),
            allow_code_drift=allow_code_drift,
            en_punct=en_punct,
            dry_run=True,
            log_fn=None,
        )
    result.detail = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
    applied, drifted = wolfdawn.parse_strings_inject_counts(res.stdout, res.stderr)
    result.would_apply = applied
    result.drifted = drifted
    result.safety_count = wolfdawn.parse_strings_inject_safety_count(res.stdout, res.stderr)

    cli_err = wolfdawn.parse_inject_cli_error(res.stdout, res.stderr)
    if cli_err and applied is None and not result.issues:
        result.error = cli_err
        return result

    if doc:
        for locator, kind, full in wolfdawn.parse_strings_inject_safety_lines(
            res.stdout, res.stderr
        ):
            line, hit_id = resolve_locator_line(doc, locator)
            hit_id = dict(hit_id)
            hit_id["json_file"] = json_name
            if not hit_id.get("sheet_name"):
                hit_id["sheet_name"] = json_name
            src = str(line.get("source") or "") if isinstance(line, dict) else ""
            txt = str(line.get("text") or "") if isinstance(line, dict) else ""
            result.issues.append(
                InjectIssue(
                    json_file=json_name,
                    kind=kind,
                    locator=locator,
                    message=full,
                    source=src,
                    text=txt,
                    hit_id=hit_id,
                )
            )
    return result


def precheck_selected(
    selected: list[str],
    *,
    manifest_entries: list[dict],
    data_dir: Path,
    originals_dir: Path,
    translated_dir: Path,
    allow_code_drift: bool = False,
    en_punct: bool = False,
    log_fn: Callable[[str], None] | None = None,
) -> PrecheckReport:
    """Dry-run inject for *selected* files and collect safety-guard issues."""
    emit = log_fn or (lambda _msg: None)
    report = PrecheckReport()
    by_json = {e["json"]: e for e in manifest_entries if e.get("json")}
    ordered = sorted(set(selected), key=lambda n: (n != NAMES_JSON, n.lower()))

    for json_name in ordered:
        if json_name == NAMES_JSON:
            # names-inject does not emit the same per-line safety locators.
            report.files.append(FilePrecheck(json_name=NAMES_JSON))
            emit(f"Precheck {NAMES_JSON}: skipped (use names-inject dry-run in log if needed)")
            continue

        entry = by_json.get(json_name)
        if not entry:
            report.files.append(
                FilePrecheck(
                    json_name,
                    error="not listed in manifest (re-run Step 0 extract)",
                )
            )
            continue
        src = translated_dir / json_name
        if not src.is_file():
            report.files.append(
                FilePrecheck(json_name, error=f"not found in {translated_dir.name}/")
            )
            continue

        emit(f"Precheck {json_name}…")
        inject_src, font_drift = repair_inject_json(src)
        strings_drift = allow_code_drift or font_drift
        if font_drift and not allow_code_drift:
            emit(
                f"  ℹ {json_name}: Fix-wrap / \\f[N] size changes — "
                "passing --allow-code-drift for dry-run"
            )
        fp = _precheck_strings_file(
            json_name,
            entry,
            inject_src,
            data_dir,
            originals_dir,
            allow_code_drift=strings_drift,
            en_punct=en_punct,
        )
        if fp.error:
            emit(f"  ✗ {json_name}: {fp.error}")
        else:
            parts = []
            if fp.would_apply is not None:
                parts.append(f"would apply {fp.would_apply}")
            if fp.issues:
                parts.append(f"{len(fp.issues)} safety skip(s)")
            elif fp.safety_count:
                parts.append(f"{fp.safety_count} safety skip(s)")
            else:
                parts.append("no safety skips")
            if fp.drifted:
                parts.append(f"{fp.drifted} drifted")
            emit(f"  · {json_name}: " + ", ".join(parts))
        report.files.append(fp)
    return report


def format_precheck_summary(report: PrecheckReport) -> str:
    """One-line status for the Step 6 precheck label."""
    safety = len(report.safety_issues)
    errors = sum(1 for f in report.files if f.error)
    parts = []
    if safety:
        parts.append(f"{safety} safety skip(s)")
    if errors:
        parts.append(f"{errors} file error(s)")
    if not parts:
        return "Precheck clean - no safety-guard skips."
    return "Precheck: " + ", ".join(parts)


def issues_for_ui(report: PrecheckReport) -> list[InjectIssue]:
    """Safety-guard issues only."""
    return list(report.safety_issues)
