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
from collections import Counter
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
_RUST_UNICODE_ESCAPE_RE = re.compile(r"\\u\{([0-9a-fA-F]+)\}")
_UNCLOSED_BRACKET_CODE_RE = re.compile(
    r"\\[A-Za-z]+\[[^\]\r\n]*(?=\r?$)", re.MULTILINE
)


def _guard_code_lists(message: str) -> tuple[list[str], list[str]] | None:
    """Extract WolfDawn's source/translation token lists from a guard message."""
    source_marker = "source has "
    translation_marker = ", translation has "
    source_at = message.find(source_marker)
    translation_at = message.find(translation_marker, source_at + len(source_marker))
    if source_at < 0 or translation_at < 0:
        return None
    source_raw = message[source_at + len(source_marker) : translation_at]
    translation_raw = message[translation_at + len(translation_marker) :]
    end = translation_raw.find("; edit the words")
    if end >= 0:
        translation_raw = translation_raw[:end]

    def decode(raw: str) -> list[str] | None:
        # Rust debug JSON uses ``\u{3000}``, which Python's JSON decoder does
        # not accept. Replace those escapes with the represented character.
        normalized = _RUST_UNICODE_ESCAPE_RE.sub(
            lambda match: chr(int(match.group(1), 16)), raw.strip()
        )
        try:
            value = json.loads(normalized)
        except Exception:
            return None
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            return None
        return value

    source_codes = decode(source_raw)
    translation_codes = decode(translation_raw)
    if source_codes is None or translation_codes is None:
        return None
    return source_codes, translation_codes


def _ordered_difference(left: list[str], right: list[str]) -> list[str]:
    remaining = Counter(right)
    difference: list[str] = []
    for token in left:
        if remaining[token] > 0:
            remaining[token] -= 1
        else:
            difference.append(token)
    return difference


def _display_code(token: str) -> str:
    if token and set(token) == {"\n"}:
        count = len(token)
        return "line break" if count == 1 else f"{count} consecutive line breaks"
    visible = token.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
    if len(visible) > 42:
        visible = visible[:24] + "…" + visible[-14:]
    return f"`{visible}`"


def _format_code_difference(tokens: list[str]) -> str:
    if not tokens:
        return "none"
    counts = Counter(tokens)
    ordered = list(dict.fromkeys(tokens))
    parts = []
    for token in ordered[:6]:
        count = counts[token]
        label = _display_code(token)
        parts.append(f"{label} ×{count}" if count > 1 else label)
    if len(ordered) > 6:
        parts.append(f"{len(ordered) - 6} more")
    return ", ".join(parts)


def explain_issue(
    kind: str,
    message: str,
    source: str,
    text: str,
) -> tuple[str, str, str]:
    """Return a concise ``(problem, difference, guidance)`` for Step 7."""
    if kind == "unrepresentable":
        unsupported: list[str] = []
        for char in text:
            try:
                char.encode("cp932")
            except UnicodeEncodeError:
                if char not in unsupported:
                    unsupported.append(char)
        shown = ", ".join(
            f"{char!r} (U+{ord(char):04X})" for char in unsupported[:6]
        )
        problem = "Translation contains characters the game cannot store"
        difference = f"Unsupported: {shown}" if shown else "Unsupported Shift-JIS text"
        return problem, difference, "Replace those characters with Japanese-game-safe text."

    unclosed = _UNCLOSED_BRACKET_CODE_RE.search(source)
    if unclosed:
        code = unclosed.group(0)
        return (
            f"Source has an unclosed control code: {_display_code(code)}",
            "The missing `]` makes WolfDawn protect the rest of that source line.",
            "Keep the affected suffix identical to the source, or correct the original event code.",
        )

    prefix = re.match(r"^(@\d+)(?:\r?\n)", source)
    if prefix and text.count(prefix.group(1)) > source.count(prefix.group(1)):
        code = prefix.group(1)
        return (
            f"Duplicate window prefix: {_display_code(code)}",
            f"The translation contains {_display_code(code)} more than once.",
            "Keep the window prefix once, at the very start of the line.",
        )

    parsed = _guard_code_lists(message)
    if parsed is None:
        return (
            "Translation control codes do not match the source",
            "WolfDawn could not safely compare this line.",
            "Edit words only; preserve every backslash code and required line break.",
        )
    source_codes, translation_codes = parsed
    missing = _ordered_difference(source_codes, translation_codes)
    extra = _ordered_difference(translation_codes, source_codes)

    changed = missing + extra
    font_only = bool(changed) and all(
        wolf_codes.WOLF_FONT_SIZE_RE.fullmatch(token) for token in changed
    )
    literal_newline = any(token.startswith(r"\n") for token in extra)
    escaped_quotes_only = bool(extra) and not missing and all(
        token == r'\"' for token in extra
    )

    if font_only:
        problem = "Font-size codes differ from the source"
        guidance = (
            "Keep this only if wrapping intentionally changed the font size; "
            "otherwise restore the source font codes."
        )
    elif literal_newline:
        problem = "Translation contains literal `\\n` text"
        guidance = "Use a real line break where the source breaks, or remove the literal `\\n`."
    elif escaped_quotes_only:
        problem = "Translation adds backslashes before quote marks"
        guidance = "Use normal quote characters without a literal backslash before them."
    elif missing and extra:
        problem = "Translation changed one or more control codes"
        guidance = "Restore the missing codes and remove the extra codes without changing their order."
    elif missing:
        problem = "Translation is missing control codes"
        guidance = "Copy the missing codes from the source into the translated text."
    elif extra:
        problem = "Translation has extra control codes"
        guidance = "Remove the extra codes unless they are an intentional font-size change."
    else:
        problem = "Control-code order differs from the source"
        guidance = "Keep the same control codes in the same order as the source."

    if missing or extra:
        difference = (
            f"Missing: {_format_code_difference(missing)}\n"
            f"Extra: {_format_code_difference(extra)}"
        )
    else:
        difference = (
            f"Expected order: {_format_code_difference(source_codes)}\n"
            f"Found order: {_format_code_difference(translation_codes)}"
        )
    return problem, difference, guidance


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
    problem: str = ""
    difference: str = ""
    guidance: str = ""

    def summary(self) -> str:
        label = self.problem or {
            "code_mismatch": "control-code mismatch",
            "unrepresentable": "not Shift-JIS encodable",
        }.get(self.kind, self.kind)
        loc = self.locator or self.json_file
        return f"{label}\n{self.json_file} · {loc}"

    def detail(self) -> str:
        parts = [f"{self.json_file} · {self.locator}".strip(" ·")]
        if self.problem:
            parts.append(f"Issue: {self.problem}")
        if self.difference:
            parts.append(self.difference)
        if self.guidance:
            parts.append(f"Fix: {self.guidance}")
        return "\n".join(parts)


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
            problem, difference, guidance = explain_issue(kind, full, src, txt)
            result.issues.append(
                InjectIssue(
                    json_file=json_name,
                    kind=kind,
                    locator=locator,
                    message=full,
                    source=src,
                    text=txt,
                    hit_id=hit_id,
                    problem=problem,
                    difference=difference,
                    guidance=guidance,
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
        inject_src, safe_code_drift = repair_inject_json(src)
        strings_drift = allow_code_drift or safe_code_drift
        if safe_code_drift and not allow_code_drift:
            emit(
                f"  ℹ {json_name}: safe font/source-code repair — "
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
    """Plain-language status for the precheck label."""
    safety = len(report.safety_issues)
    errors = sum(1 for f in report.files if f.error)
    if safety:
        result = (
            f"Check found {safety} line(s) that cannot be applied safely. "
            "Copy the AI repair skill below to fix them."
        )
        if errors:
            result += f" {errors} file(s) also could not be checked."
        return result
    if errors:
        return f"Check could not inspect {errors} file(s). See the activity log."
    return "Check complete — every reviewed translation can be applied safely."


def issues_for_ui(report: PrecheckReport) -> list[InjectIssue]:
    """Safety-guard issues only."""
    return list(report.safety_issues)


def format_ai_repair_issues(issues: list[InjectIssue]) -> str:
    """Return a complete, compact issue manifest for the AI repair skill."""
    if not issues:
        return "No issues were reported."
    blocks: list[str] = []
    for index, issue in enumerate(issues, start=1):
        font_review = issue.problem.startswith("Font-size")
        action = "REVIEW FONT-ONLY" if font_review else "FIX"
        lines = [
            f"{index}. [{action}] {issue.json_file} — {issue.locator}",
            f"   Problem: {issue.problem or issue.kind}",
        ]
        for detail_line in (issue.difference or "").splitlines():
            if detail_line:
                lines.append(f"   {detail_line}")
        if issue.guidance:
            lines.append(f"   Guidance: {issue.guidance}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
