"""WolfDawn inject orchestration for translated JSON files.

One list of files in ``translated/``, user picks some or all, each file gets a
clear pass/fail result. ``names.json`` uses ``names-inject`` (must run before
per-file ``strings-inject`` when both are selected). After names-inject, each
``strings-inject`` uses the live post-names binary as ``--base`` so name-only
DB fields (rumor boards, etc.) are not rebuilt from pristine Japanese originals.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from util.wolfdawn import codes as wolf_codes
from util.wolfdawn import db_dat_sibling
from util.wolfdawn import originals as wolf_originals
from util import wolfdawn

NAMES_JSON = "names.json"


@dataclass
class FileInjectResult:
    json_name: str
    success: bool
    summary: str
    applied: int | None = None
    detail: str = ""
    safety_skipped: int = 0
    safety_details: list[str] = field(default_factory=list)


@dataclass
class InjectReport:
    files: list[FileInjectResult] = field(default_factory=list)
    sync_failures: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.success for r in self.files) and not self.sync_failures

    @property
    def succeeded(self) -> list[FileInjectResult]:
        return [r for r in self.files if r.success]

    @property
    def failed(self) -> list[FileInjectResult]:
        return [r for r in self.files if not r.success]

    @property
    def warnings(self) -> list[FileInjectResult]:
        return [r for r in self.files if r.success and r.safety_skipped > 0]

    @property
    def safety_skipped(self) -> int:
        return sum(r.safety_skipped for r in self.files)


def list_injectable(translated_dir: Path, manifest_entries: list[dict]) -> list[str]:
    """Return sorted JSON filenames in *translated_dir* that the manifest can inject."""
    manifest_json = {e["json"] for e in manifest_entries if e.get("json")}
    if not translated_dir.is_dir():
        return []
    return sorted(
        p.name
        for p in translated_dir.glob("*.json")
        if p.is_file() and p.name in manifest_json
    )


def orig_base_for(entry: dict, data_dir: Path, originals_dir: Path) -> Path:
    """Pristine snapshot path for one manifest entry."""
    base = Path(entry["base"])
    try:
        rel = base.relative_to(data_dir)
    except ValueError:
        rel = Path(base.name)
    return originals_dir / rel


def restore_live_from_originals(
    entries: list[dict],
    data_dir: Path,
    originals_dir: Path,
) -> list[str]:
    """Copy pristine originals onto live Data/. Return warning messages."""
    warnings: list[str] = []
    for entry in entries:
        if entry.get("kind") == "names":
            continue
        orig = orig_base_for(entry, data_dir, originals_dir)
        live = Path(entry["base"])
        if not orig.exists():
            warnings.append(f"{entry['json']}: no pristine original at {orig.name}")
            continue
        try:
            if orig.is_dir():
                if live.exists():
                    shutil.rmtree(live)
                shutil.copytree(orig, live)
            else:
                live.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(orig, live)
                if entry.get("kind") == "db":
                    dat_orig = db_dat_sibling(orig)
                    dat_live = db_dat_sibling(live)
                    if dat_orig.is_file():
                        shutil.copy2(dat_orig, dat_live)
        except Exception as exc:
            warnings.append(f"{entry['json']}: could not restore live binary ({exc})")
    return warnings


def repair_inject_json(src: Path) -> tuple[Path, bool]:
    """Auto-repair WOLF inline codes in a translated JSON before inject.

    Returns ``(path, safe_code_drift)``. Automatic ``--allow-code-drift`` is
    enabled only when every difference is an intentional font change, ruby
    removal, or the translation safely closes a malformed source code.
    """
    data = json.loads(src.read_text(encoding="utf-8-sig"))
    data, repairs = wolf_codes.repair_document(data)
    if repairs:
        src.write_text(
            json.dumps(data, ensure_ascii=False, indent=4) + "\n",
            encoding="utf-8",
        )
    safe_code_drift = (
        (
            wolf_codes.document_has_font_size_drift(data)
            or wolf_codes.document_has_ruby_removals(data)
            or wolf_codes.document_has_safe_unclosed_source_repairs(data)
        )
        and not wolf_codes.document_has_non_font_code_drift(data)
    )
    return src, safe_code_drift


def names_json_has_edits(path: Path) -> bool | None:
    """Return whether a recognized names document has any pending text edits."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    names = data.get("names") if isinstance(data, dict) else None
    if not isinstance(names, list):
        return None
    return any(
        isinstance(entry, dict)
        and isinstance(entry.get("source"), str)
        and isinstance(entry.get("text"), str)
        and entry["source"] != entry["text"]
        for entry in names
    )


def _source_objects(document) -> dict[tuple[object, ...], dict]:
    found: dict[tuple[object, ...], dict] = {}

    def visit(value, path: tuple[object, ...]) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("source"), str) and isinstance(
                value.get("text"), str
            ):
                found[path] = value
            for key, child in value.items():
                visit(child, (*path, key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, (*path, index))

    visit(document, ())
    return found


def rebase_json_sources(edited_path: Path, pristine_path: Path) -> tuple[int, str | None]:
    """Refresh stale ``source`` fields by structural path, preserving translations."""
    try:
        edited = json.loads(edited_path.read_text(encoding="utf-8-sig"))
        pristine = json.loads(pristine_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return 0, f"could not read extracted JSON ({exc})"

    edited_objects = _source_objects(edited)
    pristine_objects = _source_objects(pristine)
    if not edited_objects or edited_objects.keys() != pristine_objects.keys():
        return 0, "document structure differs from the pristine extraction"

    changed = 0
    for path, edited_entry in edited_objects.items():
        pristine_source = pristine_objects[path]["source"]
        if edited_entry["source"] != pristine_source:
            edited_entry["source"] = pristine_source
            changed += 1
    if changed:
        edited_path.write_text(
            json.dumps(edited, ensure_ascii=False, indent=4) + "\n",
            encoding="utf-8",
        )
    return changed, None


def _wolf_output_snippet(stdout: str, stderr: str, *, limit: int = 400) -> str:
    text = (stdout or "").strip()
    if stderr and stderr.strip():
        text = f"{text}\n{stderr.strip()}".strip() if text else stderr.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _safety_details(stdout: str, stderr: str) -> list[str]:
    labels = {
        "code_mismatch": "control-code mismatch",
        "unrepresentable": "text is not representable in the game encoding",
    }
    return [
        f"{locator} — {labels.get(kind, 'safety guard')}"
        for locator, kind, _full_line in wolfdawn.parse_strings_inject_safety_lines(
            stdout, stderr
        )
    ]


def _interpret_strings_result(json_name: str, res: wolfdawn.WolfResult) -> FileInjectResult:
    cli_err = wolfdawn.parse_inject_cli_error(res.stdout, res.stderr)
    applied, drifted = wolfdawn.parse_strings_inject_counts(res.stdout, res.stderr)
    safety = wolfdawn.parse_strings_inject_safety_count(res.stdout, res.stderr)
    mismatches = wolfdawn.parse_strings_inject_mismatches(res.stdout, res.stderr)
    safety_details = _safety_details(res.stdout, res.stderr)
    detail = _wolf_output_snippet(res.stdout, res.stderr)

    # Exit 2 with a positive applied count still wrote the good lines; treat as success
    # and surface safety skips in the summary (see inject_had_applied).
    if wolfdawn.inject_had_applied(applied):
        msg = f"applied {applied} line(s)"
        if drifted:
            msg += f" ({drifted} drifted)"
        if safety:
            msg += f" ({safety} skipped by safety guard)"
        return FileInjectResult(
            json_name,
            True,
            msg,
            applied=applied,
            detail=detail,
            safety_skipped=safety or 0,
            safety_details=safety_details,
        )

    if not res.ok:
        reason = cli_err or f"wolf exited {res.returncode}"
        return FileInjectResult(json_name, False, reason, applied=applied, detail=detail)

    if (drifted or 0) > 0:
        return FileInjectResult(
            json_name,
            False,
            (
                f"0 applied, {drifted} drifted "
                "(JSON source was not found in the injection baseline)"
            ),
            applied=0,
            detail=detail,
        )

    if safety or mismatches:
        parts = []
        if safety:
            parts.append(f"{safety} line(s) skipped by safety guard")
        elif mismatches:
            parts.append(f"{len(mismatches)} control-code mismatch(es)")
        return FileInjectResult(
            json_name,
            False,
            "; ".join(parts),
            applied=0,
            detail=detail,
            safety_skipped=safety or 0,
            safety_details=safety_details,
        )

    return FileInjectResult(json_name, True, "no changes needed", applied=0, detail=detail)


def _interpret_names_result(json_name: str, res: wolfdawn.WolfResult) -> FileInjectResult:
    cli_err = wolfdawn.parse_inject_cli_error(res.stdout, res.stderr)
    applied, drifted = wolfdawn.parse_names_inject_counts(res.stdout, res.stderr)
    safety = wolfdawn.parse_strings_inject_safety_count(res.stdout, res.stderr)
    safety_details = _safety_details(res.stdout, res.stderr)
    detail = _wolf_output_snippet(res.stdout, res.stderr)

    if wolfdawn.inject_had_applied(applied):
        msg = f"applied {applied} name change(s)"
        if drifted:
            msg += f" ({drifted} unmatched)"
        if safety:
            msg += f" ({safety} skipped by safety guard)"
        return FileInjectResult(
            json_name,
            True,
            msg,
            applied=applied,
            detail=detail,
            safety_skipped=safety or 0,
            safety_details=safety_details,
        )

    if not res.ok:
        reason = cli_err or f"wolf exited {res.returncode}"
        return FileInjectResult(json_name, False, reason, applied=applied, detail=detail)

    if res.ok and (drifted or 0) > 0:
        return FileInjectResult(
            json_name,
            False,
            (
                f"0 applied, {drifted} unmatched "
                "(extract again from pristine data in Step 1)"
            ),
            applied=0,
            detail=detail,
        )

    return FileInjectResult(
        json_name,
        False,
        _STALE_NAMES_MSG,
        applied=0,
        detail=detail,
    )


_STALE_NAMES_MSG = (
    "0 name changes would apply even though names.json contains edits. Its source "
    "values or wolf_json/originals/ do not match the pristine game data. Rebuilt "
    "from .wolf archives automatically when possible; if this persists, extract "
    "again from pristine data in Step 1."
)


def _prepare_for_names_inject(
    names_src: Path,
    manifest_entries: list[dict],
    data_dir: Path,
    originals_dir: Path,
    game_root: Path,
    log_fn: Callable[[str], None] | None = None,
    *,
    allow_code_drift: bool = False,
) -> str | None:
    """Restore live Data/ and ensure names-inject can match Japanese sources."""
    emit = log_fn or (lambda _msg: None)

    def _restore() -> None:
        for warning in restore_live_from_originals(
            manifest_entries, data_dir, originals_dir
        ):
            emit(f"  ⚠ {warning}")

    _restore()
    would_apply = wolf_originals.names_inject_would_apply(
        names_src, data_dir, allow_code_drift=allow_code_drift
    )
    if wolfdawn.inject_had_applied(would_apply):
        return None

    emit("  ⚠ names.json would apply 0 changes — rebuilding pristine originals…")
    if wolf_originals.rebuild_originals_from_archives(
        game_root, originals_dir, force=True, log_fn=log_fn
    ):
        _restore()
        would_apply = wolf_originals.names_inject_would_apply(
            names_src, data_dir, allow_code_drift=allow_code_drift
        )
        if wolfdawn.inject_had_applied(would_apply):
            emit(f"  ✓ ready — dry run would apply {would_apply} name change(s)")
            return None

    return _STALE_NAMES_MSG


def _inject_names(
    names_src: Path,
    data_dir: Path,
    *,
    allow_code_drift: bool,
    en_punct: bool,
    log_fn: Callable[[str], None] | None = None,
) -> FileInjectResult:
    emit = log_fn or (lambda _msg: None)
    would_apply = wolf_originals.names_inject_would_apply(
        names_src, data_dir, allow_code_drift=allow_code_drift
    )
    if not wolfdawn.inject_had_applied(would_apply):
        return FileInjectResult(
            NAMES_JSON,
            False,
            (
                "inject refused — dry run would apply 0 name changes "
                "(live Data/ still lacks Japanese sources; rebuild originals first)"
            ),
        )

    emit(f"  dry run: {would_apply} name change(s) pending")
    res = wolfdawn.names_inject(
        str(names_src),
        str(data_dir),
        allow_code_drift=allow_code_drift,
        en_punct=en_punct,
        log_fn=None,
    )
    result = _interpret_names_result(NAMES_JSON, res)
    if not result.success:
        return result

    remaining = wolf_originals.names_inject_would_apply(
        names_src, data_dir, allow_code_drift=allow_code_drift
    )
    if wolfdawn.inject_had_applied(remaining):
        result = FileInjectResult(
            NAMES_JSON,
            False,
            (
                f"only partial apply — {result.summary}, but dry run still shows "
                f"{remaining} pending (restart Game.exe and report this)"
            ),
            applied=result.applied,
            detail=result.detail,
            safety_skipped=result.safety_skipped,
            safety_details=result.safety_details,
        )
    elif result.success and wolfdawn.inject_had_applied(result.applied):
        result = FileInjectResult(
            NAMES_JSON,
            True,
            result.summary + " — restart Game.exe to see changes",
            applied=result.applied,
            detail=result.detail,
            safety_skipped=result.safety_skipped,
            safety_details=result.safety_details,
        )
    return result


def _inject_strings(
    json_name: str,
    entry: dict,
    inject_src: Path,
    data_dir: Path,
    originals_dir: Path,
    *,
    allow_code_drift: bool,
    en_punct: bool,
    base_path: Path | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> FileInjectResult:
    """Inject one strings JSON.

    ``base_path`` defaults to the pristine original. Pass the live binary when
    names-inject already ran in this batch so name-only fields are preserved.
    """
    orig = orig_base_for(entry, data_dir, originals_dir)
    out = entry["base"]
    base = base_path if base_path is not None else orig
    if not base.exists():
        return FileInjectResult(
            json_name,
            False,
            f"no inject base at {base} (extract again in Step 1)",
        )
    if not orig.exists():
        return FileInjectResult(
            json_name,
            False,
            f"no pristine original at {orig} (extract again in Step 1)",
        )

    if entry.get("kind") == "db" and not db_dat_sibling(base).is_file():
        return FileInjectResult(
            json_name,
            False,
            "missing database .dat pair beside inject base (extract again in Step 1)",
        )

    # WolfDawn reports stale entries whose ``source == text`` as merely
    # "untranslated" rather than drifted. Validate both classes directly
    # against a fresh pristine extraction while preserving translated text.
    probe = wolfdawn.strings_inject(
        str(inject_src),
        str(orig),
        out,
        allow_code_drift=allow_code_drift,
        en_punct=en_punct,
        dry_run=True,
        log_fn=None,
    )
    _probe_applied, probe_drifted = wolfdawn.parse_strings_inject_counts(
        probe.stdout, probe.stderr
    )
    probe_untranslated = wolfdawn.parse_strings_inject_untranslated(
        probe.stdout, probe.stderr
    )
    if (probe_drifted or 0) > 0 or (probe_untranslated or 0) > 0:
        emit = log_fn or (lambda _message: None)
        with tempfile.TemporaryDirectory() as raw:
            pristine_json = Path(raw) / json_name
            extracted = wolfdawn.strings_extract(
                str(orig), str(pristine_json), log_fn=None
            )
            if not extracted.ok or not pristine_json.is_file():
                return FileInjectResult(
                    json_name,
                    False,
                    "could not validate JSON sources against the pristine original",
                )
            rebased, error = rebase_json_sources(inject_src, pristine_json)
        if error:
            return FileInjectResult(
                json_name,
                False,
                f"automatic source refresh refused: {error}",
            )
        if rebased:
            emit(
                f"  ⚠ {json_name}: refreshed {rebased} stale source field(s) "
                "from the pristine original"
            )
            probe = wolfdawn.strings_inject(
                str(inject_src),
                str(orig),
                out,
                allow_code_drift=allow_code_drift,
                en_punct=en_punct,
                dry_run=True,
                log_fn=None,
            )
            _probe_applied, probe_drifted = wolfdawn.parse_strings_inject_counts(
                probe.stdout, probe.stderr
            )
    if (probe_drifted or 0) > 0:
        return FileInjectResult(
            json_name,
            False,
            (
                f"source validation left {probe_drifted} drifted line(s); "
                "re-extract from pristine data"
            ),
        )

    res = wolfdawn.strings_inject(
        str(inject_src),
        str(base),
        out,
        allow_code_drift=allow_code_drift,
        en_punct=en_punct,
        log_fn=None,
    )
    return _interpret_strings_result(json_name, res)


def ensure_db_dat_snapshots(
    entries: list[dict],
    data_dir: Path,
    originals_dir: Path,
) -> None:
    """Backfill missing database ``.dat`` files in *originals_dir* from live Data/."""
    for entry in entries:
        if entry.get("kind") != "db":
            continue
        proj_orig = orig_base_for(entry, data_dir, originals_dir)
        dat_orig = db_dat_sibling(proj_orig)
        if dat_orig.exists():
            continue
        dat_live = db_dat_sibling(Path(entry["base"]))
        if not dat_live.is_file():
            continue
        dat_orig.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dat_live, dat_orig)


def inject_selected(
    selected: list[str],
    *,
    manifest_entries: list[dict],
    data_dir: Path,
    originals_dir: Path,
    translated_dir: Path,
    game_root: Path,
    allow_code_drift: bool = False,
    en_punct: bool = False,
    log_fn: Callable[[str], None] | None = None,
) -> InjectReport:
    """Inject *selected* translated JSON files. Returns a per-file report."""
    emit = log_fn or (lambda _msg: None)
    report = InjectReport()
    if not selected:
        return report

    by_json = {e["json"]: e for e in manifest_entries if e.get("json")}
    ordered = sorted(set(selected), key=lambda n: (n != NAMES_JSON, n.lower()))

    missing_manifest = [n for n in ordered if n not in by_json]
    missing_translated = [
        n for n in ordered if not (translated_dir / n).is_file()
    ]
    for name in missing_manifest:
        report.files.append(
            FileInjectResult(name, False, "not listed in manifest (extract again in Step 1)")
        )
    for name in missing_translated:
        if name in by_json:
            report.files.append(
                FileInjectResult(name, False, f"not found in {translated_dir.name}/")
            )

    todo = [
        n for n in ordered
        if n in by_json and (translated_dir / n).is_file()
    ]
    if not todo:
        return report

    def emit_result(result: FileInjectResult) -> None:
        if not result.success:
            prefix = "  ✗ "
        elif result.safety_skipped:
            prefix = "  ⚠ "
        else:
            prefix = "  ✓ "
        emit(prefix + f"{result.json_name}: {result.summary}")
        for warning in result.safety_details[:10]:
            emit(f"      ↳ {warning}")
        hidden = len(result.safety_details) - 10
        if hidden > 0:
            emit(f"      … {hidden} more skipped line(s)")
        if result.safety_skipped:
            emit("      Open Step 7 Check to review and edit skipped lines.")

    names_applied = False
    if NAMES_JSON in todo:
        names_src = translated_dir / NAMES_JSON
        names_edited = names_json_has_edits(names_src)
        if names_edited is False:
            result = FileInjectResult(NAMES_JSON, True, "no changes needed", applied=0)
            report.files.append(result)
            emit_result(result)
            todo = [n for n in todo if n != NAMES_JSON]
        else:
            emit("Preparing live Data/ for names.json…")
        names_drift = allow_code_drift
        if names_edited is not False and not names_drift:
            try:
                names_doc = json.loads(names_src.read_text(encoding="utf-8-sig"))
            except Exception:
                names_doc = None
            if (
                isinstance(names_doc, dict)
                and (
                    wolf_codes.names_doc_has_font_size_drift(names_doc)
                    or wolf_codes.names_doc_has_ruby_removals(names_doc)
                )
                and not wolf_codes.names_doc_has_non_font_code_drift(names_doc)
            ):
                names_drift = True
                emit(
                    "  ℹ names use safe font/ruby code changes — "
                    "passing --allow-code-drift for names-inject"
                )
        if names_edited is not False:
            prep_error = _prepare_for_names_inject(
                names_src,
                manifest_entries,
                data_dir,
                originals_dir,
                game_root,
                log_fn=log_fn,
                allow_code_drift=names_drift,
            )
            if prep_error:
                result = FileInjectResult(NAMES_JSON, False, prep_error)
                report.files.append(result)
                emit_result(result)
                todo = [n for n in todo if n != NAMES_JSON]
            else:
                emit(f"Injecting {NAMES_JSON}…")
                result = _inject_names(
                    names_src,
                    data_dir,
                    allow_code_drift=names_drift,
                    en_punct=en_punct,
                    log_fn=log_fn,
                )
                report.files.append(result)
                emit_result(result)
                names_applied = result.success

    strings_todo = [n for n in todo if n != NAMES_JSON]
    if strings_todo:
        ensure_db_dat_snapshots(manifest_entries, data_dir, originals_dir)
        if names_applied:
            emit(
                "  ℹ using live Data/ as strings-inject base "
                "(preserve name-only fields from names-inject)"
            )

    for json_name in strings_todo:
        entry = by_json[json_name]
        inject_src, safe_code_drift = repair_inject_json(translated_dir / json_name)
        strings_drift = allow_code_drift or safe_code_drift
        if safe_code_drift and not allow_code_drift:
            emit(
                f"  ℹ {json_name}: safe font/ruby/source-code change — "
                "passing --allow-code-drift for strings-inject"
            )
        emit(f"Injecting {json_name}…")
        # After names-inject, live binaries already hold EN name-only fields.
        # Rebuilding from pristine JP originals would wipe those (rumor boards, etc.).
        live_base = Path(entry["base"]) if names_applied else None
        result = _inject_strings(
            json_name,
            entry,
            inject_src,
            data_dir,
            originals_dir,
            allow_code_drift=strings_drift,
            en_punct=en_punct,
            base_path=live_base,
            log_fn=log_fn,
        )
        report.files.append(result)
        emit_result(result)

    return report


def format_report_dialog(report: InjectReport) -> tuple[str, str] | None:
    """Return a concise problem dialog, or ``None`` on clean success.

    Success details already go to the workflow log; a per-file success popup
    overflows the screen on large games.
    """
    if report.failed or report.sync_failures or report.warnings:
        lines: list[str] = []
        ok_n = len(report.succeeded)
        if report.failed or report.sync_failures:
            if ok_n:
                lines.append(f"{ok_n} file(s) succeeded; failures:")
        else:
            lines.append(
                f"Translations were applied, but {report.safety_skipped} line(s) "
                "were left unchanged by the safety guard:"
            )
        for result in report.warnings:
            lines.append(f"⚠ {result.json_name}: {result.summary}")
            for warning in result.safety_details[:20]:
                lines.append(f"    {warning}")
            hidden = len(result.safety_details) - 20
            if hidden > 0:
                lines.append(f"    … {hidden} more skipped line(s)")
        if report.warnings:
            lines.append("Open Step 7 Check to review and edit the skipped lines.")
        for r in report.failed:
            lines.append(f"✗ {r.json_name}: {r.summary}")
            if r.detail:
                lines.append(f"    {r.detail}")
        for name, err in report.sync_failures:
            lines.append(f"✗ sync {name}: {err}")
        title = (
            "Inject finished with errors"
            if report.failed or report.sync_failures
            else "Inject completed with warnings"
        )
        return title, "\n".join(lines)
    return None


def format_report_status(report: InjectReport) -> str:
    """One-line status for the log / status bar after inject."""
    ok_n = len(report.succeeded)
    fail_n = len(report.failed) + len(report.sync_failures)
    if fail_n:
        warning_note = (
            f", {report.safety_skipped} skipped" if report.safety_skipped else ""
        )
        return f"Inject: {ok_n} ok, {fail_n} failed{warning_note} (see dialog)."
    if report.safety_skipped:
        return (
            f"⚠ Inject completed with warnings: {ok_n} file(s), "
            f"{report.safety_skipped} line(s) skipped (see dialog)."
        )
    if ok_n:
        return f"Inject complete: {ok_n} file(s)."
    return "Inject: nothing was injected."
