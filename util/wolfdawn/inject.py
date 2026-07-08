"""WolfDawn inject orchestration for translated JSON files.

One list of files in ``translated/``, user picks some or all, each file gets a
clear pass/fail result. ``names.json`` uses ``names-inject`` (must run before
per-file ``strings-inject`` when both are selected).
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


def repair_inject_json(src: Path) -> Path:
    """Auto-repair WOLF inline codes in a translated JSON before inject."""
    data = json.loads(src.read_text(encoding="utf-8-sig"))
    data, repairs = wolf_codes.repair_document(data)
    if repairs:
        src.write_text(
            json.dumps(data, ensure_ascii=False, indent=4) + "\n",
            encoding="utf-8",
        )
    return src


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
    untranslated = wolfdawn.parse_strings_inject_untranslated(res.stdout, res.stderr)
    mismatches = wolfdawn.parse_strings_inject_mismatches(res.stdout, res.stderr)
    detail = _wolf_output_snippet(res.stdout, res.stderr)

    if not res.ok:
        reason = cli_err or f"wolf exited {res.returncode}"
        return FileInjectResult(json_name, False, reason, applied=applied, detail=detail)

    if wolfdawn.inject_had_applied(applied):
        msg = f"applied {applied} line(s)"
        if drifted:
            msg += f" ({drifted} drifted)"
        if untranslated:
            msg += f" ({untranslated} skipped by safety guard)"
        return FileInjectResult(json_name, True, msg, applied=applied, detail=detail)

    if (drifted or 0) > 0:
        return FileInjectResult(
            json_name,
            False,
            f"0 applied, {drifted} drifted (live Data/ no longer matches Japanese sources)",
            applied=0,
            detail=detail,
        )

    if untranslated or mismatches:
        parts = []
        if untranslated:
            parts.append(f"{untranslated} line(s) skipped by safety guard")
        if mismatches:
            parts.append(f"{len(mismatches)} control-code mismatch(es)")
        return FileInjectResult(
            json_name, False, "; ".join(parts), applied=0, detail=detail
        )

    return FileInjectResult(json_name, True, "no changes needed", applied=0, detail=detail)


def _interpret_names_result(json_name: str, res: wolfdawn.WolfResult) -> FileInjectResult:
    cli_err = wolfdawn.parse_inject_cli_error(res.stdout, res.stderr)
    applied, drifted = wolfdawn.parse_names_inject_counts(res.stdout, res.stderr)
    detail = _wolf_output_snippet(res.stdout, res.stderr)

    if not res.ok:
        reason = cli_err or f"wolf exited {res.returncode}"
        return FileInjectResult(json_name, False, reason, applied=applied, detail=detail)

    if wolfdawn.inject_had_applied(applied):
        msg = f"applied {applied} name change(s)"
        if drifted:
            msg += f" ({drifted} unmatched)"
        return FileInjectResult(json_name, True, msg, applied=applied, detail=detail)

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
) -> str | None:
    """Restore live Data/ and ensure names-inject can match Japanese sources."""
    emit = log_fn or (lambda _msg: None)

    def _restore() -> None:
        for warning in restore_live_from_originals(
            manifest_entries, data_dir, originals_dir
        ):
            emit(f"  ⚠ {warning}")

    _restore()
    would_apply = wolf_originals.names_inject_would_apply(names_src, data_dir)
    if wolfdawn.inject_had_applied(would_apply):
        return None

    emit("  ⚠ names.json would apply 0 changes — rebuilding pristine originals…")
    if wolf_originals.rebuild_originals_from_archives(
        game_root, originals_dir, force=True, log_fn=log_fn
    ):
        _restore()
        would_apply = wolf_originals.names_inject_would_apply(names_src, data_dir)
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
    would_apply = wolf_originals.names_inject_would_apply(names_src, data_dir)
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

    remaining = wolf_originals.names_inject_would_apply(names_src, data_dir)
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
) -> FileInjectResult:
    orig = orig_base_for(entry, data_dir, originals_dir)
    out = entry["base"]
    if not orig.exists():
        return FileInjectResult(
            json_name,
            False,
            f"no pristine original at {orig} (re-run Step 0 extract)",
        )

    if entry.get("kind") == "db" and not db_dat_sibling(orig).is_file():
        return FileInjectResult(
            json_name,
            False,
            "missing database .dat pair in originals (re-run Step 0 extract)",
        )

    res = wolfdawn.strings_inject(
        str(inject_src),
        str(orig),
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

    if NAMES_JSON in todo:
        emit("Preparing live Data/ for names.json…")
        names_src = translated_dir / NAMES_JSON
        prep_error = _prepare_for_names_inject(
            names_src,
            manifest_entries,
            data_dir,
            originals_dir,
            game_root,
            log_fn=log_fn,
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
                allow_code_drift=allow_code_drift,
                en_punct=en_punct,
                log_fn=log_fn,
            )
            report.files.append(result)
            emit(("  ✓ " if result.success else "  ✗ ") + f"{NAMES_JSON}: {result.summary}")

    strings_todo = [n for n in todo if n != NAMES_JSON]
    if strings_todo:
        ensure_db_dat_snapshots(manifest_entries, data_dir, originals_dir)

    for json_name in strings_todo:
        entry = by_json[json_name]
        inject_src = repair_inject_json(translated_dir / json_name)
        emit(f"Injecting {json_name}…")
        result = _inject_strings(
            json_name,
            entry,
            inject_src,
            data_dir,
            originals_dir,
            allow_code_drift=allow_code_drift,
            en_punct=en_punct,
        )
        report.files.append(result)
        emit(("  ✓ " if result.success else "  ✗ ") + f"{json_name}: {result.summary}")

    return report


def format_report_dialog(report: InjectReport) -> tuple[str, str]:
    """Return (title, body) for a completion dialog."""
    if report.ok and report.succeeded:
        title = "Inject complete"
        lines = [f"✓ {r.json_name}: {r.summary}" for r in report.succeeded]
    elif report.failed or report.sync_failures:
        title = "Inject finished with errors"
        lines = []
        for r in report.succeeded:
            lines.append(f"✓ {r.json_name}: {r.summary}")
        for r in report.failed:
            lines.append(f"✗ {r.json_name}: {r.summary}")
            if r.detail:
                lines.append(f"    {r.detail}")
        for name, err in report.sync_failures:
            lines.append(f"✗ sync {name}: {err}")
    else:
        title = "Inject"
        lines = ["Nothing was injected."]
    return title, "\n".join(lines)
