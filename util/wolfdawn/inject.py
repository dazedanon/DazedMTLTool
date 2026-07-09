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

    Returns ``(path, has_font_size_drift)``. Font-size drift is detected after
    repair so intentional ``\\f[N]`` shrinks from Fix-wrap survive and inject
    can auto-pass ``--allow-code-drift``.
    """
    data = json.loads(src.read_text(encoding="utf-8-sig"))
    data, repairs = wolf_codes.repair_document(data)
    if repairs:
        src.write_text(
            json.dumps(data, ensure_ascii=False, indent=4) + "\n",
            encoding="utf-8",
        )
    return src, wolf_codes.document_has_font_size_drift(data)


def _wolf_output_snippet(stdout: str, stderr: str, *, limit: int = 400) -> str:
    text = (stdout or "").strip()
    if stderr and stderr.strip():
        text = f"{text}\n{stderr.strip()}".strip() if text else stderr.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _interpret_strings_result(json_name: str, res: wolfdawn.WolfResult) -> FileInjectResult:
    cli_err = wolfdawn.parse_inject_cli_error(res.stdout, res.stderr)
    applied, drifted = wolfdawn.parse_strings_inject_counts(res.stdout, res.stderr)
    safety = wolfdawn.parse_strings_inject_safety_count(res.stdout, res.stderr)
    mismatches = wolfdawn.parse_strings_inject_mismatches(res.stdout, res.stderr)
    detail = _wolf_output_snippet(res.stdout, res.stderr)

    # Exit 2 with a positive applied count still wrote the good lines; treat as success
    # and surface safety skips in the summary (see inject_had_applied).
    if wolfdawn.inject_had_applied(applied):
        msg = f"applied {applied} line(s)"
        if drifted:
            msg += f" ({drifted} drifted)"
        if safety:
            msg += f" ({safety} skipped by safety guard)"
        return FileInjectResult(json_name, True, msg, applied=applied, detail=detail)

    if not res.ok:
        reason = cli_err or f"wolf exited {res.returncode}"
        return FileInjectResult(json_name, False, reason, applied=applied, detail=detail)

    if (drifted or 0) > 0:
        return FileInjectResult(
            json_name,
            False,
            f"0 applied, {drifted} drifted (live Data/ no longer matches Japanese sources)",
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
            json_name, False, "; ".join(parts), applied=0, detail=detail
        )

    return FileInjectResult(json_name, True, "no changes needed", applied=0, detail=detail)


def _interpret_names_result(json_name: str, res: wolfdawn.WolfResult) -> FileInjectResult:
    cli_err = wolfdawn.parse_inject_cli_error(res.stdout, res.stderr)
    applied, drifted = wolfdawn.parse_names_inject_counts(res.stdout, res.stderr)
    safety = wolfdawn.parse_strings_inject_safety_count(res.stdout, res.stderr)
    detail = _wolf_output_snippet(res.stdout, res.stderr)

    if wolfdawn.inject_had_applied(applied):
        msg = f"applied {applied} name change(s)"
        if drifted:
            msg += f" ({drifted} unmatched)"
        if safety:
            msg += f" ({safety} skipped by safety guard)"
        return FileInjectResult(json_name, True, msg, applied=applied, detail=detail)

    if not res.ok:
        reason = cli_err or f"wolf exited {res.returncode}"
        return FileInjectResult(json_name, False, reason, applied=applied, detail=detail)

    if res.ok and (drifted or 0) > 0:
        return FileInjectResult(
            json_name,
            False,
            (
                f"0 applied, {drifted} unmatched "
                "(re-run Step 0 extract on the untranslated game)"
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
    "0 name changes would apply. wolf_json/originals/ still holds old English "
    "instead of Japanese sources (usually after a previous inject). Rebuilt from "
    ".wolf archives automatically when possible; if this persists, re-run Step 0 "
    "on the untranslated game."
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
        )
    elif result.success and wolfdawn.inject_had_applied(result.applied):
        result = FileInjectResult(
            NAMES_JSON,
            True,
            result.summary + " — restart Game.exe to see changes",
            applied=result.applied,
            detail=result.detail,
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
            f"no inject base at {base} (re-run Step 0 extract)",
        )
    if not orig.exists():
        return FileInjectResult(
            json_name,
            False,
            f"no pristine original at {orig} (re-run Step 0 extract)",
        )

    if entry.get("kind") == "db" and not db_dat_sibling(base).is_file():
        return FileInjectResult(
            json_name,
            False,
            "missing database .dat pair beside inject base (re-run Step 0 extract)",
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
            FileInjectResult(name, False, "not listed in manifest (re-run Step 0 extract)")
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

    names_applied = False
    if NAMES_JSON in todo:
        emit("Preparing live Data/ for names.json…")
        names_src = translated_dir / NAMES_JSON
        names_drift = allow_code_drift
        if not names_drift:
            try:
                names_doc = json.loads(names_src.read_text(encoding="utf-8-sig"))
            except Exception:
                names_doc = None
            if isinstance(names_doc, dict) and wolf_codes.names_doc_has_font_size_drift(
                names_doc
            ):
                names_drift = True
                emit(
                    "  ℹ names-wrap changed \\f[N] sizes — "
                    "passing --allow-code-drift for names-inject"
                )
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
            emit(f"  ✗ {NAMES_JSON}: {result.summary}")
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
            emit(("  ✓ " if result.success else "  ✗ ") + f"{NAMES_JSON}: {result.summary}")
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
        inject_src, font_drift = repair_inject_json(translated_dir / json_name)
        strings_drift = allow_code_drift or font_drift
        if font_drift and not allow_code_drift:
            emit(
                f"  ℹ {json_name}: Fix-wrap / \\f[N] size changes — "
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
        )
        report.files.append(result)
        emit(("  ✓ " if result.success else "  ✗ ") + f"{json_name}: {result.summary}")

    return report


def format_report_dialog(report: InjectReport) -> tuple[str, str] | None:
    """Return ``(title, body)`` for a failure dialog, or ``None`` on full success.

    Success details already go to the workflow log; a per-file success popup
    overflows the screen on large games.
    """
    if report.failed or report.sync_failures:
        lines: list[str] = []
        ok_n = len(report.succeeded)
        if ok_n:
            lines.append(f"{ok_n} file(s) succeeded; failures:")
        for r in report.failed:
            lines.append(f"✗ {r.json_name}: {r.summary}")
            if r.detail:
                lines.append(f"    {r.detail}")
        for name, err in report.sync_failures:
            lines.append(f"✗ sync {name}: {err}")
        return "Inject finished with errors", "\n".join(lines)
    return None


def format_report_status(report: InjectReport) -> str:
    """One-line status for the log / status bar after inject."""
    ok_n = len(report.succeeded)
    fail_n = len(report.failed) + len(report.sync_failures)
    if fail_n:
        return f"Inject: {ok_n} ok, {fail_n} failed (see dialog)."
    if ok_n:
        return f"Inject complete: {ok_n} file(s)."
    return "Inject: nothing was injected."
