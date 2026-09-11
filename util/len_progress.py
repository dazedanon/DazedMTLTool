"""Small, portable progress snapshots counted from saved Len translation records."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from util.len_translation import LenProject, _prepare_local_work, _validate_project, _write_atomic

PHASES = {
    "preparation": "Preparation", "extraction": "Extraction", "translation": "Translation",
    "injection": "Injection", "qa": "QA", "patch": "Patch",
}
STATES = {
    "pending": "Pending", "active": "In progress", "complete": "Done",
    "blocked": "Blocked", "out_of_scope": "Out of scope",
}


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def review_fingerprint(source: bytes, translation: bytes) -> str:
    """Bind a completed review to both the exact source and the exact output."""
    return _digest((_digest(source) + ":" + _digest(translation)).encode("ascii"))


def _scope(project: LenProject) -> str:
    # Mode and translate/continue/QA navigation do not change the game's corpus.
    value = {"include_images": project.include_images, "instructions": project.instructions,
             "include_glossary_base": project.include_glossary_base}
    return _digest(json.dumps(value, sort_keys=True).encode("utf-8"))


def _line(value, label):
    if not isinstance(value, str) or len(value) > 240 or any(c in value for c in "\r\n\0"):
        raise ValueError(f"{label} must be one short line (up to 240 characters).")
    return value.strip()


def _artifact(game: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("Progress artifact paths must be relative to the game folder.")
    path = (game / relative).resolve()
    if path == game.resolve() / ".dazedtl/len-method/progress.json":
        raise ValueError("The progress snapshot cannot watch itself.")
    if not path.is_relative_to(game.resolve()) or not path.is_file():
        raise ValueError(f"Missing progress artifact inside the game folder: {relative}")
    return path


def _read_artifact(game: Path, relative: str, evidence: dict) -> bytes:
    path = _artifact(game, relative)
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
        raise ValueError(f"Progress artifact changed while reading: {relative}")
    key = path.relative_to(game.resolve()).as_posix()
    evidence[key] = {"path": key, "sha256": _digest(raw),
                     "size": after.st_size, "mtime_ns": after.st_mtime_ns}
    return raw


def _count_records(project, relative, kind, evidence):
    if relative is None:
        return {"total": None, "translated": 0, "reviewed": 0}
    exported = json.loads(_read_artifact(project.game_root, relative, evidence).decode("utf-8-sig"))
    if (not isinstance(exported, dict) or type(exported.get("complete")) is not bool
            or not isinstance(exported.get("units"), list)):
        raise ValueError(f"{kind} records require a complete boolean and a units list.")
    unique = {}
    translated = reviewed = 0
    for unit in exported["units"]:
        if not isinstance(unit, dict):
            raise ValueError("Each progress unit must be an object with a stable id.")
        identity = _line(unit.get("id"), "Unit id")
        if not identity:
            raise ValueError("Progress unit ids cannot be empty.")
        if identity in unique:
            if unit != unique[identity]:
                raise ValueError(f"Conflicting progress records for unit {identity}.")
            continue
        unique[identity] = unit
        source = unit.get("source")
        output = unit.get("translation")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"Unit {identity} needs a nonempty source.")
        if output is not None and not isinstance(output, str):
            raise ValueError(f"Unit {identity} translation must be text or null.")
        if kind == "images":
            source_bytes = _read_artifact(project.game_root, source, evidence)
            output_bytes = _read_artifact(project.game_root, output, evidence) if output else None
            if not source_bytes:
                raise ValueError(f"Image source is empty: {source}")
            output_bytes = output_bytes or None
            if output and _artifact(project.game_root, source) == _artifact(project.game_root, output):
                raise ValueError("Image progress needs separate original and translated files.")
        else:
            source_bytes = source.encode("utf-8")
            output_bytes = output.encode("utf-8") if output and output.strip() else None
        # A saved output for an older source or an older review never counts as
        # current completion. These hashes travel with the saved result/review.
        current = output_bytes is not None and unit.get("translated_from_sha256") == _digest(source_bytes)
        translated += current
        reviewed += current and unit.get("reviewed_sha256") == review_fingerprint(source_bytes, output_bytes)
    return {"total": len(unique) if exported["complete"] else None,
            "discovered": len(unique), "translated": translated, "reviewed": reviewed,
            "corpus_sha256": _digest(json.dumps(sorted((key, value["source"]) for key, value in unique.items()), ensure_ascii=False).encode())}


def empty_progress(project: LenProject) -> dict:
    return {
        "schema": 1, "updated_at": None, "scope_sha256": _scope(project), "phase": None,
        "phases": dict.fromkeys(PHASES, "pending"),
        "metrics": {key: {"total": None, "translated": 0, "reviewed": 0} for key in ("text", "images")},
        "blocker": "", "next_action": "", "evidence": [],
        "timing": {}, "history": [], "estimates": {},
    }


def initialize_progress(project: LenProject) -> None:
    path = project.workspace / "progress.json"
    if not path.exists():
        _write_atomic(path, json.dumps(empty_progress(project), indent=2) + "\n")


def _validate_snapshot(value):
    required = {"schema", "updated_at", "scope_sha256", "phase", "phases", "metrics", "blocker", "next_action", "evidence"}
    if (not isinstance(value, dict) or required - value.keys()
            or type(value.get("schema")) is not int or value["schema"] != 1):
        raise ValueError("Unsupported progress snapshot. Update it with progress-update.")
    if value.get("phase") is not None and (not isinstance(value["phase"], str) or value["phase"] not in PHASES):
        raise ValueError("Unknown progress phase.")
    phases = value.get("phases")
    if (not isinstance(phases, dict) or set(phases) != set(PHASES)
            or any(not isinstance(v, str) or v not in STATES for v in phases.values())):
        raise ValueError("Invalid progress phase states.")
    if not isinstance(value.get("metrics"), dict):
        raise ValueError("Missing progress metrics.")
    for kind in ("text", "images"):
        metric = value.get("metrics", {}).get(kind)
        if not isinstance(metric, dict) or {"total", "translated", "reviewed"} - metric.keys():
            raise ValueError("Missing progress counts.")
        total, translated, reviewed = (metric.get(k) for k in ("total", "translated", "reviewed"))
        if (any(type(v) is not int or v < 0 for v in (translated, reviewed))
                or total is not None and (type(total) is not int or total < 0 or translated > total)
                or reviewed > translated):
            raise ValueError("Progress counts must satisfy 0 <= reviewed <= translated <= total.")
        discovered = metric.get("discovered", total)
        if discovered is not None and (type(discovered) is not int or discovered < translated
                                       or total is not None and discovered != total):
            raise ValueError("Discovered counts must include translated units and match an audited total.")
    _validate_estimates(value.get("estimates", {}))
    _validate_timing(value.get("timing", {}))
    history = value.get("history", [])
    if not isinstance(history, list) or len(history) > 20:
        raise ValueError("Invalid progress history.")
    for sample in history:
        if not isinstance(sample, dict) or set(sample) != {"corpus", "timing", "translated", "reviewed"}:
            raise ValueError("Invalid progress history sample.")
        _validate_timing(sample["timing"])
        if not isinstance(sample["corpus"], str) or any(type(sample[k]) is not int or sample[k] < 0 for k in ("translated", "reviewed")):
            raise ValueError("Invalid progress history counts.")
    for key in ("blocker", "next_action"):
        _line(value.get(key), key)
    if not isinstance(value.get("scope_sha256"), str) or not isinstance(value.get("evidence"), list):
        raise ValueError("Invalid progress evidence.")
    for item in value["evidence"]:
        if (not isinstance(item, dict) or not isinstance(item.get("path"), str)
                or not isinstance(item.get("sha256"), str)
                or type(item.get("size")) is not int or type(item.get("mtime_ns")) is not int):
            raise ValueError("Invalid progress artifact fingerprint.")
    if value.get("updated_at") is not None:
        if not isinstance(value["updated_at"], str):
            raise ValueError("Invalid progress timestamp.")
        stamp = datetime.fromisoformat(value["updated_at"])
        if stamp.tzinfo is None:
            raise ValueError("Progress timestamps must include a time zone.")


def update_progress(project: LenProject, report: dict) -> dict:
    """Replace one complete report; derive counts from persisted unit exports."""
    _validate_project(project)
    allowed = {"phase", "phases", "text", "images", "inputs", "blocker", "next_action", "timing", "estimates"}
    if not isinstance(report, dict) or report.keys() - allowed:
        raise ValueError("Progress reports accept phase, phases, text, images, inputs, blocker, next_action, timing and estimates.")
    snapshot = empty_progress(project)
    phase = report.get("phase")
    if phase is not None and (not isinstance(phase, str) or phase not in PHASES):
        raise ValueError("Choose a known progress phase.")
    phases = report.get("phases", {})
    if (not isinstance(phases, dict) or phases.keys() - PHASES.keys()
            or any(not isinstance(state, str) or state not in STATES for state in phases.values())):
        raise ValueError("Choose known phase names and states.")
    snapshot["phase"] = phase
    snapshot["phases"].update(phases)
    if phase:
        snapshot["phases"][phase] = phases.get(phase, "active")
        if snapshot["phases"][phase] not in {"active", "blocked"}:
            raise ValueError("The current phase must be active or blocked.")
    for key in ("blocker", "next_action"):
        snapshot[key] = _line(report.get(key, ""), key)
    evidence = {}
    inputs = report.get("inputs", [])
    if not isinstance(inputs, list):
        raise ValueError("Progress inputs must be a list of source/evidence file paths.")
    for relative in inputs:
        _read_artifact(project.game_root, relative, evidence)
    snapshot["metrics"]["text"] = _count_records(project, report.get("text"), "text", evidence)
    if project.include_images:
        snapshot["metrics"]["images"] = _count_records(project, report.get("images"), "images", evidence)
    elif report.get("images") is not None:
        raise ValueError("Images are outside the selected project scope.")
    if snapshot["phases"]["translation"] == "complete":
        required = [snapshot["metrics"]["text"]]
        if project.include_images:
            required.append(snapshot["metrics"]["images"])
        if any(m["total"] is None or m["translated"] != m["total"] for m in required):
            raise ValueError("Translation cannot be complete while scoped totals are unknown or units remain untranslated.")
    _validate_timing(report.get("timing", {}))
    _validate_estimates(report.get("estimates", {}))
    snapshot["timing"] = report.get("timing", {})
    snapshot["estimates"] = report.get("estimates", {})
    previous_path = project.workspace / "progress.json"
    previous = read_progress(project) if previous_path.exists() else empty_progress(project)
    metric = snapshot["metrics"]["text"]
    corpus = metric.get("corpus_sha256", "")
    history = previous.get("history", []) if previous["scope_sha256"] == snapshot["scope_sha256"] else []
    history = [entry for entry in history if entry["corpus"] == corpus]
    if history and (any(snapshot["timing"].get(k, 0) < v for k, v in history[-1]["timing"].items())
                    or any(metric[k] < history[-1][k] for k in ("translated", "reviewed"))):
        history = []  # A reset or invalidated result needs new throughput samples.
    sample = {"corpus": corpus, "timing": snapshot["timing"],
              "translated": metric["translated"], "reviewed": metric["reviewed"]}
    if corpus and snapshot["timing"] and (not history or sample != history[-1]):
        history = (history + [sample])[-20:]
    snapshot["history"] = history
    snapshot["evidence"] = sorted(evidence.values(), key=lambda item: item["path"])
    snapshot["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _validate_snapshot(snapshot)
    project.workspace.mkdir(parents=True, exist_ok=True)
    _prepare_local_work(project)
    _write_atomic(project.workspace / "progress.json", json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    return snapshot


def read_progress(project: LenProject, *, check_hashes=True) -> dict:
    """Read the last report with freshness warnings, without changing saved work."""
    _validate_project(project)
    path = project.workspace / "progress.json"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("Progress must be stored in a regular progress.json file.")
    value = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else empty_progress(project)
    _validate_snapshot(value)
    warnings = []
    if value["updated_at"] and value["scope_sha256"] != _scope(project):
        warnings.append("Project scope changed. Recheck the saved results and update progress.")
    for item in value["evidence"]:
        try:
            artifact = _artifact(project.game_root, item["path"])
            stat = artifact.stat()
            if (_digest(artifact.read_bytes()) != item["sha256"] if check_hashes else
                    (stat.st_size, stat.st_mtime_ns) != (item["size"], item["mtime_ns"])):
                raise ValueError("Changed artifact")
        except (OSError, ValueError):
            warnings.append("Saved records or source inputs need rechecking. Validate results and update progress.")
            break
    return {**value, "warnings": warnings}


def metric_display(metric: dict, counter: str, *, excluded=False) -> tuple[int, str, str]:
    """Return a percentage, bar label and count label without inventing a total."""
    if excluded:
        return 0, "Out of scope", ""
    done, total = metric[counter], metric["total"]
    provisional = total is None
    if provisional:
        total = metric.get("discovered")
        if total is None:
            return 0, "Not measured", f"{done:,} / ?" if done else ""
    if total == 0:
        return 0, "No units", "0 / 0"
    percent = min(100, 100 * done // total)
    return percent, f"{percent}%" + (" discovered" if provisional else ""), f"{done:,} / {total:,}" + (" discovered; coverage unaudited" if provisional else "")


def _validate_timing(timing):
    if not isinstance(timing, dict) or timing.keys() - {"translated", "reviewed"}:
        raise ValueError("Timing accepts cumulative active seconds for translated and reviewed text.")
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in timing.values()):
        raise ValueError("Active seconds must be finite and nonnegative.")


def _validate_estimates(estimates):
    if not isinstance(estimates, dict) or estimates.keys() - PHASES.keys():
        raise ValueError("Estimates must name known phases.")
    for estimate in estimates.values():
        if not isinstance(estimate, dict) or set(estimate) != {"low_minutes", "high_minutes", "basis"}:
            raise ValueError("Each estimate needs low_minutes, high_minutes and a short basis.")
        low, high = estimate["low_minutes"], estimate["high_minutes"]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (low, high)) or not 0 <= low <= high:
            raise ValueError("Remaining minutes must be finite and satisfy 0 <= low <= high.")
        if not _line(estimate["basis"], "Estimate basis"):
            raise ValueError("Describe the estimate's basis and exclusions.")


def estimate_display(snapshot):
    """Present bounded active-work estimates, never a fabricated completion time."""
    if snapshot.get("warnings"):
        return "Estimates paused: saved evidence needs rechecking."
    if snapshot.get("blocker"):
        return "Estimates paused while blocked. " + snapshot["blocker"]
    rows = []
    history = snapshot.get("history", [])
    metric = snapshot["metrics"]["text"]
    total = metric.get("discovered", metric["total"])
    for counter, title in (("translated", "Text translation"), ("reviewed", "Text review")):
        if total is None or total <= metric[counter] or len(history) < 2:
            continue
        current = history[-1]
        candidates = [entry for entry in history[:-1]
                      if entry["corpus"] == current["corpus"] and counter in entry["timing"]]
        if not candidates or counter not in current["timing"]:
            continue
        first = candidates[0]
        seconds = current["timing"][counter] - first["timing"][counter]
        completed = current[counter] - first[counter]
        if seconds < 60 or completed <= 0:
            continue
        minutes = (total - metric[counter]) * seconds / completed / 60
        rows.append(f"{title}: about {max(1, math.floor(minutes * .7))}–{max(1, math.ceil(minutes * 1.5))} active minutes "
                    f"for the discovered corpus (recent rate; planning range).")
    for phase, estimate in snapshot.get("estimates", {}).items():
        if snapshot["phases"][phase] not in {"complete", "out_of_scope"}:
            rows.append(f"{PHASES[phase]}: {estimate['low_minutes']:g}–{estimate['high_minutes']:g} active minutes. {estimate['basis']}")
    return "\n".join(rows) if rows else "Estimate unavailable: record active work and remaining phase estimates at the next milestone."
