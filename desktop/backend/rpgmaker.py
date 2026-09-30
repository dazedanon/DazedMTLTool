"""Production RPG Maker run plans and a credential-free worker controller."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from util.paths import PROJECT_ROOT, PROMPT_PATH, GLOSSARY_BASE_PATH, TRANSLATION_CONTEXTS_PATH, SFX_REFERENCE_PATH, runtime_data_file
from util.rpgmaker_profiles import DB_FILES, EVENT_FILES_EXACT, PHASE0_CONFIG, PHASE1_CONFIG
from .budget import MODEL
from .project import atomic_json, digest

PLAN_VERSION = 1
DEFAULT_SETTINGS = {"width": 60, "faceWidth": 50, "listWidth": 100, "noteWidth": 75, "batchsize": 8,
                    "FIRSTLINESPEAKERS": False, "INLINE401SPEAKERS": False, "FACENAME101": False,
                    "AUTONAMEPOPUP101": False, "CODE408": False}
ENGINE_SOURCES = ("modules/rpgmakermvmz.py", "util/translation.py", "util/dazedwrap.py", "util/vocab.py",
                  "util/skills/system.py", "util/skills/contexts.py", "util/rpgmaker_profiles.py", "util/runtime_text.py",
                  "desktop/backend/rpgmaker.py", "desktop/backend/rpgmaker_worker.py", "desktop/backend/review_store.py")


def engine_signature():
    return digest(b"".join((PROJECT_ROOT / name).read_bytes() for name in ENGINE_SOURCES))


def normalize_settings(settings):
    if not isinstance(settings, dict) or set(settings) - set(DEFAULT_SETTINGS):
        raise ValueError("Unsupported RPG Maker settings.")
    result = {**DEFAULT_SETTINGS, **settings}
    for key, value in result.items():
        if isinstance(DEFAULT_SETTINGS[key], bool):
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be enabled or disabled.")
        elif not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= (8 if key == "batchsize" else 500):
            raise ValueError(f"{key} is outside the supported range.")
    result["faceWidth"] = min(result["width"], result["faceWidth"])
    return result


def file_phase(name):
    if name in DB_FILES:
        return "database"
    if name in EVENT_FILES_EXACT or re.fullmatch(r"Map\d+\.json", name):
        return "dialogue"
    return None


def profile(phase, settings):
    if phase not in {"database", "dialogue", "standard"}:
        raise ValueError("Choose database text, dialogue and choices, or standard text.")
    config = dict(PHASE0_CONFIG if phase == "database" else PHASE1_CONFIG)
    config.update({key: value for key, value in settings.items() if isinstance(value, bool) and (key != "CODE408" or phase != "database")})
    return {"engine": "rpgmakermvmz", "version": 1, "config": config,
            "enabled_plugins_357": [], "enabled_patterns_355655": []}


def import_context(source: Path, destination: Path):
    """Copy portable guidance without invoking migration helpers on the game."""
    metadata = source / ".dazedtl"
    if metadata.is_symlink():
        raise ValueError("Project guidance cannot be imported through a symbolic link.")
    destination.mkdir(parents=True, exist_ok=True)
    candidates = [metadata / "glossary.txt", metadata / "settings.json"]
    if (metadata / "skills").is_symlink():
        raise ValueError("Project skills cannot be imported through a symbolic link.")
    candidates.extend((metadata / "skills").glob("*.md"))
    for path in candidates:
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError("A project guidance file is not a regular file below 1 MB.")
        target = destination / path.relative_to(metadata)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())


def create_plan(project, folder: Path, job_dir: Path, files, phase, settings, request_limit, mode="offline", workspace=None):
    settings = normalize_settings(settings)
    if not isinstance(files, list) or not files or len(set(files)) != len(files):
        raise ValueError("Select one or more unique files.")
    available = {entry["name"]: entry["sha256"] for entry in project["files"]}
    if any(name not in available or file_phase(name) is None or (phase != "standard" and file_phase(name) != phase) for name in files):
        raise ValueError("Select files belonging to this project and translation phase.")
    if not isinstance(request_limit, int) or isinstance(request_limit, bool) or not 1 <= request_limit <= 25:
        raise ValueError("Choose 1–25 new API requests per attempt.")
    input_hashes = dict(available)
    working_files = project.get("working_files", {})
    input_hashes.update({name: details["sha256"] for name, details in working_files.items() if name in available})
    dependencies = []
    if phase != "database" and "Actors.json" in available and "Actors.json" not in files and "Actors.json" not in working_files:
        dependencies.append("Actors.json")
    files = [*files, *dependencies]
    return {"version": PLAN_VERSION, "engine": "rpgmakermvmz", "mode": mode, "engine_signature": engine_signature(),
            "phase": phase, "files": sorted(files, key=lambda name: (file_phase(name) != "database", name)), "settings": settings, "profile": profile(phase, settings),
            "request_limit": request_limit, "source_revision": project["revision"],
            "working_revision": project.get("working_revision", 0),
            "data_relative": project["data_relative"], "input_hashes": input_hashes,
            "working_files": sorted(name for name in working_files if name in available), "dependencies": dependencies,
            "context": read_context(folder / "context", project.get("guidance", "")),
            "base_prompt": runtime_data_file(PROMPT_PATH, workspace).read_text(encoding="utf-8"),
            "base_glossary": runtime_data_file(GLOSSARY_BASE_PATH, workspace).read_text(encoding="utf-8"),
            "translation_contexts": runtime_data_file(TRANSLATION_CONTEXTS_PATH, workspace).read_text(encoding="utf-8"), "sfx_content": runtime_data_file(SFX_REFERENCE_PATH, workspace).read_text(encoding="utf-8")}


def read_context(folder: Path, fallback=""):
    result = {"glossary.txt": "", "skills/game.md": fallback, "skills/quirks.md": ""}
    if folder.exists():
        for path in folder.rglob("*"):
            if path.is_file() and not path.is_symlink() and (path.name == "glossary.txt" or path.suffix == ".md"):
                result[path.relative_to(folder).as_posix()] = path.read_text(encoding="utf-8-sig")
    return result


def prepare_workspace(project_dir: Path, job_dir: Path, plan, stopped):
    if plan["version"] != PLAN_VERSION or plan["engine_signature"] != engine_signature():
        raise ValueError("The production adapter changed. Create a new run so saved work is not resumed with different engine logic.")
    prepared = job_dir / "prepared.json"
    for relative in ("inputs", "files", "translated", "receipts", "context", "game", "game/.dazedtl", "game/.dazedtl/skills"):
        if (job_dir / relative).is_symlink():
            raise ValueError("An isolated run directory was replaced by a symbolic link.")
    if prepared.is_file():
        saved = json.loads(prepared.read_text())
        if saved["plan_hash"] != digest(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()):
            raise ValueError("The saved run plan changed. Create a new run.")
        for name, expected in plan["input_hashes"].items():
            path = job_dir / "inputs" / name
            if path.is_symlink() or digest(path.read_bytes()) != expected:
                raise ValueError("A frozen input changed; this run cannot safely resume.")
        for name, expected in saved.get("context_hashes", {}).items():
            path = job_dir / "context" / name
            if path.is_symlink() or digest(path.read_bytes()) != expected:
                raise ValueError("Frozen translation context changed; create a new run.")
        for name, text in plan["context"].items():
            if name == "glossary.txt":
                continue  # The engine deliberately harvests translated names.
            path = job_dir / "game/.dazedtl" / name
            if path.is_symlink() or path.read_text(encoding="utf-8") != text:
                raise ValueError("This run's frozen game instructions changed.")
        return
    source = project_dir / "source" / plan["data_relative"]
    for directory in ("inputs", "files", "translated", "receipts", "context", "log", "game/.dazedtl/skills"):
        (job_dir / directory).mkdir(parents=True, exist_ok=True)
    for name, expected in plan["input_hashes"].items():
        if stopped():
            raise InterruptedError("Stopped while preparing isolated files.")
        path = project_dir / "working" / name if name in plan["working_files"] else source / name
        raw = path.read_bytes()
        if path.is_symlink() or digest(raw) != expected:
            raise ValueError("The project snapshot changed. Import it again before running the adapter.")
        (job_dir / "inputs" / name).write_bytes(raw)
        (job_dir / "files" / name).write_bytes(raw)
    for name, content in plan["context"].items():
        target = job_dir / "game/.dazedtl" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    for name, key in (("system.md", "base_prompt"), ("base-glossary.txt", "base_glossary"), ("translation_contexts.json", "translation_contexts")):
        (job_dir / "context" / name).write_text(plan[key], encoding="utf-8")
    if "sfx_content" in plan:
        (job_dir / "context/sfx.json").write_text(plan["sfx_content"], encoding="utf-8")
    else:  # Previously saved plans used the bundled reference hash.
        if digest(SFX_REFERENCE_PATH.read_bytes()) != plan["sfx_sha256"]:
            raise ValueError("The shared sound-effect reference changed after planning.")
        shutil.copyfile(SFX_REFERENCE_PATH, job_dir / "context/sfx.json")
    for relative in ("js/plugins.js", "www/js/plugins.js"):
        path = project_dir / "source" / relative
        if path.is_file():
            target = job_dir / "game" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    atomic_json(prepared, {"plan_hash": digest(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()),
                          "context_hashes": {p.name: digest(p.read_bytes()) for p in (job_dir / "context").iterdir() if p.is_file()}})


def offline_completion(params, filename=""):
    """Valid, visibly synthetic output exercises the actual parser/validator."""
    raw = params["messages"][-1]["content"]
    decoder = json.JSONDecoder()
    values = None
    for match in re.finditer(r"\{", raw):
        try:
            candidate, _end = decoder.raw_decode(raw[match.start():])
            if isinstance(candidate, dict) and candidate and all(re.fullmatch(r"Line\d+", key) for key in candidate):
                values = candidate
                break
        except (ValueError, TypeError):
            continue
    if values is None:
        raise ValueError("The production adapter sent an unrecognized text payload.")
    translated = []
    for value in values.values():
        # Retain placeholders, numbers and Latin actor substitutions. The actual
        # production layer restores runtime codes and performs line wrapping.
        speaker = re.match(r"^(\[[^\n]*?\]:\s*)(.*)", str(value), re.DOTALL)
        prefix, body = (speaker.group(1), speaker.group(2)) if speaker else ("", str(value))
        retained = re.sub(r"[\u3000-\u303f\u3040-\u30ff\u3400-\u9fff\uff61-\uff9f]", "", body)
        if filename in {"Actors.json", "speakers"}:
            # Actor substitutions must remain distinct from the ordinary fake
            # dialogue marker, or restoring a name could replace the marker.
            suffix = digest(str(value).encode())[:8].translate(str.maketrans("0123456789abcdef", "abcdefghijklmnop"))
            marker = "Offline actor " + suffix
        else:
            marker = "Offline test text"
        translated.append(prefix + marker + (" " + retained.strip() if retained.strip() else ""))
    return {"text": json.dumps({"translations": translated}, ensure_ascii=False), "prompt_tokens": 0, "completion_tokens": 0}


def run_worker(job_dir: Path, plan, completed_files, speakers_done, generation, provider, stopped, event_callback):
    if plan["engine_signature"] != engine_signature():
        raise ValueError("Engine code changed after this run was prepared.")
    if (provider is not None) != (plan.get("mode", "offline") == "live"):
        raise ValueError("The saved execution method does not match this worker's transport.")
    invocation = {**plan, "completed_files": completed_files, "speakers_done": speakers_done}
    atomic_json(job_dir / "attempt.json", invocation)
    for name in plan["files"]:
        if name not in completed_files and (job_dir / "translated" / name).is_file():
            shutil.copyfile(job_dir / "translated" / name, job_dir / "files" / name)
    env = {key: value for key, value in os.environ.items() if key in {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "TIKTOKEN_CACHE_DIR"
    }}
    env["PYTHONIOENCODING"] = "utf-8"
    command = [sys.executable, "-u", str(Path(__file__).with_name("rpgmaker_worker.py")), str(job_dir / "attempt.json")]
    new_requests = 0
    outcome = {"status": "failed", "message": "The production worker exited without a completion record."}
    failure = None
    stderr_path = job_dir / "log/startup.txt"
    with stderr_path.open("a", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, cwd=job_dir,
                                   env=env, text=True, encoding="utf-8", bufsize=1)
        try:
            for line in process.stdout:
                event = json.loads(line)
                kind = event.get("event")
                if kind in {"stopped", "failed"}:
                    outcome = {"status": "failed" if failure else kind, "message": failure or event.get("message", "")}
                    break
                reply = {}
                if stopped() and kind != "file_done":
                    reply = {"stop": True, "message": "Stopped after the current request. Saved work is ready to resume."}
                elif kind == "request":
                    params = event["params"]
                    key = digest(json.dumps({"params": params, "generation": generation.get(event.get("file"), 0)}, sort_keys=True, ensure_ascii=False).encode())
                    receipt_path = job_dir / "receipts" / (key + ".json")
                    if receipt_path.is_file():
                        response = json.loads(receipt_path.read_text())["response"]
                        reply = {"response": {**response, "prompt_tokens": 0, "completion_tokens": 0}}
                        event_callback({"event": "replayed", "file": event.get("file")})
                    elif provider is not None and new_requests >= plan["request_limit"]:
                        reply = {"stop": True, "message": f"Paused at the {plan['request_limit']}-request allowance. Resume to continue within the remaining global budget."}
                    else:
                        try:
                            response = provider(params) if provider is not None else offline_completion(params, event.get("file", ""))
                            atomic_json(receipt_path, {"file": event.get("file"), "response": response, "request_sha256": key})
                            reply = {"response": response}
                            if provider is not None:
                                new_requests += 1
                            event_callback({"event": "request_done", "file": event.get("file"), "new_requests": new_requests})
                        except Exception as exc:
                            message = str(exc) if isinstance(exc, ValueError) else f"{type(exc).__name__}: provider request failed; no automatic retry."
                            reply = {"error": message}
                            failure = message
                            outcome = {"status": "failed", "message": message}
                else:
                    event_callback(event)
                    if kind == "file_error":
                        failure = event["message"]
                    if kind == "complete":
                        outcome = {"status": "complete", "message": "Production translation completed. Review the generated files before export."}
                process.stdin.write(json.dumps(reply, ensure_ascii=False) + "\n")
                process.stdin.flush()
            process.stdin.close()
            returncode = process.wait(timeout=10)
            if returncode and outcome["status"] == "complete":
                outcome = {"status": "failed", "message": "The engine exited with an error after writing files. Saved outputs are retained."}
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            process.stdout.close()
            if not process.stdin.closed:
                process.stdin.close()
    return {**outcome, "new_requests": new_requests}
