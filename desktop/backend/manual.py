"""Durable manual translation jobs backed by the shared production runner."""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from util.paths import PROJECT_ROOT, PROMPT_PATH, GLOSSARY_BASE_PATH, TRANSLATION_CONTEXTS_PATH, SFX_REFERENCE_PATH, runtime_data_file
from util.translation_task import TRANSLATION_MODULE_SPECS, translation_module
from .project import atomic_json, digest
from .settings import SettingsStore


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def relative_file(value):
    if not isinstance(value, str):
        raise ValueError("Invalid relative file path.")
    path = PurePosixPath(value)
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or path.is_absolute() or any(part in {".", ".."} for part in path.parts) or path.as_posix() != value:
        raise ValueError("Invalid relative file path.")
    return path


def signature(engine):
    module_path = next(spec[2] for spec in TRANSLATION_MODULE_SPECS if spec[0] == engine)
    paths = [PROJECT_ROOT / (module_path.replace(".", "/") + ".py"), *sorted((PROJECT_ROOT / "util").rglob("*.py")),
             *sorted(Path(__file__).parent.glob("manual*.py"))]
    return digest(b"".join(path.read_bytes() for path in paths))


class ManualJobs:
    def __init__(self, workspace, lock, *, allow_providers=False):
        self.workspace = Path(workspace)
        self.root = self.workspace / "manual"
        self.lock = lock
        self.allow_providers = allow_providers
        self.jobs = {}
        self.worker = None
        self.process = None
        self.stopping = threading.Event()
        self.active = ""
        self.load_saved()

    def load_saved(self):
        for path in (self.root / "jobs").glob("*/job.json"):
            job = json.loads(path.read_text(encoding="utf-8"))
            if job['id'] in self.jobs:
                continue
            if job.get("version") not in {1, 2}:
                raise ValueError("A manual run requires a newer desktop version.")
            if job["status"] in {"running", "waiting"}:
                job.update(status="interrupted", approval=None, message="The application closed during this run. Resume its saved workspace when ready.")
                atomic_json(path, job)
            self.jobs[job["id"]] = job

    def running(self):
        return bool(self.worker and self.worker.is_alive())

    def folder(self, identity):
        if identity not in self.jobs:
            raise ValueError("This manual run is not available.")
        return self.root / "jobs" / identity

    def save(self, job):
        job["updated"] = timestamp()
        atomic_json(self.folder(job["id"]) / "job.json", job)

    def state(self):
        with self.lock:
            return json.loads(json.dumps({"engines": [{"name": spec[0], "extensions": spec[1]} for spec in TRANSLATION_MODULE_SPECS],
                                         "jobs": sorted(self.jobs.values(), key=lambda job: job["created"], reverse=True),
                                         "active": self.active if self.running() else None, "allow_providers": self.allow_providers}))

    def inspect(self, source, engine, *, managed=False):
        extensions = translation_module(engine)[1]
        root = Path(source).expanduser().resolve(strict=True)
        managed_root = (root.parent.parent == self.workspace / "workflows" and root.name == "files" or
                        root.parent.parent == self.workspace / "asset-projects" and root.name == "translation-input" and engine == "Image Text")
        if not root.is_dir() or (not managed or not managed_root) and (root.is_relative_to(self.workspace) or self.workspace.is_relative_to(root)):
            raise ValueError("Choose an input folder outside the desktop workspace.")
        files = []
        total_bytes = 0
        for directory, folders, names in os.walk(root, followlinks=False):
            folders[:] = sorted(name for name in folders if not name.startswith(".") and not (Path(directory) / name).is_symlink())
            for name in sorted(names):
                if name.startswith(".") or not name.endswith(extensions):
                    continue
                path = Path(directory) / name
                if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000_000:
                    raise ValueError("Input files must be regular files below 100 MB.")
                relative = path.relative_to(root).as_posix()
                relative_file(relative)
                raw = path.read_bytes()
                files.append({"name": relative, "bytes": len(raw), "sha256": digest(raw)})
                total_bytes += len(raw)
                if len(files) > 10000 or total_bytes > 2_000_000_000:
                    raise ValueError("Choose a smaller input folder (up to 10,000 files or 2 GB).")
        if not files:
            raise ValueError("No files in this folder match the selected engine.")
        revision = digest(json.dumps(files, sort_keys=True).encode())
        return {"source": str(root), "engine": engine, "files": files, "revision": revision}

    def start(self, source, engine, files, revision, mode="estimate", context_source="", *, workflow=None, managed=False, configuration=None, launch=True):
        with self.lock:
            if self.running():
                raise ValueError("A manual run is already active.")
            if mode not in {"estimate", "offline", "translate", "batch", "speakers"}:
                raise ValueError("Choose a supported translation mode.")
            if mode in {"translate", "batch", "speakers"} and not self.allow_providers:
                raise ValueError("Full provider execution is disabled for this migration build. Local estimates and offline tests are available.")
            if mode == "speakers" and engine != "RPG Maker MV/MZ":
                raise ValueError("Explicit speaker collection is available for RPG Maker MV/MZ. WolfDawn checks speakers automatically.")
            inventory = self.inspect(source, engine, managed=managed or workflow is not None)
            if revision != inventory["revision"]:
                raise ValueError("The input files changed. Refresh the file list before starting.")
            names = {item["name"] for item in inventory["files"]}
            if not isinstance(files, list) or not files or not all(isinstance(name, str) and name in names for name in files) or len(set(files)) != len(files):
                raise ValueError("Select unique files from this input folder.")
            settings = SettingsStore(self.workspace)
            described = configuration or settings.describe()
            values = dict(described["values"])
            if workflow is not None:
                from util.engine_options import validate_engine_options
                if engine == "RPG Maker MV/MZ":
                    described["engines"]["rpgmakermvmz"] = validate_engine_options({"rpgmakermvmz": workflow["engine_options"]})["rpgmakermvmz"]
                values.update(workflow["widths"])
            active_key = described["active_key"]
            environment = settings.runtime(values, active_key) if active_key else None
            if mode in {"translate", "batch", "speakers"} and environment is None:
                raise ValueError("Configure an API credential in Settings first.")
            if environment:
                values["api"] = environment["api"]
            if mode == 'batch':
                from util.batch_providers import detect_batch_provider
                if not detect_batch_provider(values['model'], api_url=values['api'], api_provider=values['API_PROVIDER']):
                    raise ValueError('This endpoint does not support provider Batch jobs. Choose a supported provider before starting.')
            if mode == "offline":
                values.update(API_PROVIDER="openai", api="https://api.openai.com/v1", model="gpt-6-luna")
            runtime_profile = None
            if engine == "RPG Maker MV/MZ":
                overrides = described["engines"]["rpgmakermvmz"]
                runtime_profile = {"engine": "rpgmakermvmz", "version": 1,
                                   "config": {key: value for key, value in overrides.items() if not key.startswith("ENABLED_")},
                                   "enabled_plugins_357": overrides.get("ENABLED_PLUGINS_357", []),
                                   "enabled_patterns_355655": overrides.get("ENABLED_PATTERNS_355655", [])}
            plan = {"version": 1, **inventory, "selected": files, "mode": mode, "settings": values, "key_name": active_key,
                    "engines": described["engines"], "runtime_profile": runtime_profile, "signature": signature(engine),
                    "context_source": str(Path(context_source).expanduser().resolve(strict=True)) if context_source else "", "workflow": workflow}
            identity = uuid.uuid4().hex
            directory = self.root / "jobs" / identity
            directory.mkdir(parents=True)
            try:
                self._snapshot_context(directory, plan)
                if workflow is not None:
                    cache = self.workspace / "workflows" / workflow["id"] / "log/var_translation_map.json"
                    if cache.exists():
                        if cache.is_symlink() or cache.stat().st_size > 10_000_000:
                            raise ValueError("The phase variable cache must be a regular file below 10 MB.")
                        raw = cache.read_bytes()
                        json.loads(raw)
                        (directory / "seed").mkdir()
                        (directory / "seed/var_translation_map.json").write_bytes(raw)
                        plan["context_hashes"]["seed/var_translation_map.json"] = digest(raw)
                atomic_json(directory / "plan.json", plan)
                job = {"version": 1, "id": identity, "created": timestamp(), "updated": timestamp(), "source": inventory["source"],
                       "engine": engine, "mode": mode, "model": values["model"], "files": files, "status": "running", "phase": "preparing",
                       "message": "Preparing an isolated copy of the input files.", "completed": [], "errors": {}, "mismatches": {}, "approval": None,
                       "progress": None, "estimate": None, "log": [], "exports": [], "outputs": {}, "plan_hash": digest((directory / "plan.json").read_bytes())}
                self.jobs[identity] = job
                if not launch:
                    job.update(status='stopped', message='Imported batch recovery is ready for review.')
                if launch:
                    self.save(job)
                    self._launch(job, False)
            except Exception:
                if identity not in self.jobs:
                    shutil.rmtree(directory)
                raise
            return json.loads(json.dumps(job))

    def _snapshot_context(self, directory, plan, workspace=None):
        from .rpgmaker import import_context
        context = directory / "context"
        context.mkdir()
        for name, path in (("system.md", PROMPT_PATH), ("base-glossary.txt", GLOSSARY_BASE_PATH),
                           ("translation_contexts.json", TRANSLATION_CONTEXTS_PATH), ("sfx.json", SFX_REFERENCE_PATH)):
            shutil.copyfile(runtime_data_file(path, workspace or getattr(self, "workspace", None)), context / name)
        game = directory / "game"
        metadata = game / ".dazedtl"
        metadata.mkdir(parents=True)
        if plan["context_source"]:
            source = Path(plan["context_source"])
            if not source.is_dir() or (source / "skills").is_symlink():
                raise ValueError("Choose a regular game context folder.")
            import_context(source, metadata)
            for name in ("glossary.txt", "translation_quirks.txt"):
                path = source / name
                destination = metadata / ("skills/quirks.md" if name == "translation_quirks.txt" else name)
                if path.is_file() and not destination.exists():
                    if path.is_symlink() or path.stat().st_size > 1_000_000:
                        raise ValueError("Legacy guidance must be a regular file below 1 MB.")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, destination)
            for path in (source / "skills").glob("*.md"):
                destination = metadata / "skills" / ("game.md" if path.name == "translation.md" else path.name)
                if not destination.exists():
                    if path.is_symlink() or path.stat().st_size > 1_000_000:
                        raise ValueError("Legacy skills must be regular files below 1 MB.")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, destination)
            # Read-only engine context needed for face/plugin speaker detection.
            from util.wolfdawn.cdb_context import SIDECAR_NAME
            for relative in ("js/plugins.js", "www/js/plugins.js", f"wolf_json/{SIDECAR_NAME}", "wolf_json/db_profile.json"):
                path = source / relative
                if path.is_file():
                    if path.is_symlink() or not path.resolve().is_relative_to(source) or path.stat().st_size > 10_000_000:
                        raise ValueError("Plugin configuration must be a regular file below 10 MB.")
                    target = game / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
        if (plan.get("workflow") or {}).get("wolf_speakers"):
            atomic_json(context / "wolf_speakers.json", plan["workflow"]["wolf_speakers"])
        (metadata / "skills").mkdir(exist_ok=True)
        (metadata / "glossary.txt").touch(exist_ok=True)
        plan["context_hashes"] = {path.relative_to(directory).as_posix(): digest(path.read_bytes()) for folder in (context, game)
                                  for path in folder.rglob("*") if path.is_file()}

    def _launch(self, job, resume):
        self.stopping.clear()
        self.active = job["id"]
        job.update(status="running", approval=None, message="Resuming saved work." if resume else job["message"])
        job["errors"] = {}
        self.save(job)
        self.worker = threading.Thread(target=self._run, args=(job["id"], resume), daemon=False)
        self.worker.start()

    def _run(self, identity, resume):
        job = self.jobs[identity]
        directory = self.folder(identity)
        try:
            plan_path = directory / "plan.json"
            if plan_path.is_symlink() or digest(plan_path.read_bytes()) != job["plan_hash"]:
                raise ValueError("The saved plan changed. Start a new run.")
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            if plan["signature"] != signature(plan["engine"]):
                raise ValueError("The engine changed. Start a new run to keep saved requests tied to their original code.")
            for name, expected in plan["context_hashes"].items():
                if resume and name == "game/.dazedtl/glossary.txt":
                    continue  # The engine deliberately harvests translated names.
                path = directory / name
                if path.is_symlink() or digest(path.read_bytes()) != expected:
                    raise ValueError("This run's frozen instructions changed. Start a new run.")
            for folder in ("inputs", "files", "translated", "log"):
                path = directory / folder
                if path.is_symlink():
                    raise ValueError("An isolated run folder became a symbolic link.")
                path.mkdir(exist_ok=True)
            prepared = directory / "prepared.json"
            seed = directory / "seed/var_translation_map.json"
            if not prepared.is_file() and seed.is_file():
                shutil.copyfile(seed, directory / "log/var_translation_map.json")
            for item in plan["files"]:
                if self.stopping.is_set():
                    raise InterruptedError("Stopped while preparing the isolated inputs.")
                name = item["name"]
                original = directory / "inputs" / name if prepared.is_file() else Path(plan["source"]) / name
                source_root = directory / "inputs" if prepared.is_file() else Path(plan["source"])
                if original.is_symlink() or not original.resolve().is_relative_to(source_root) or digest(original.read_bytes()) != item["sha256"]:
                    raise ValueError("An input changed after planning. Refresh the file list and start a new run.")
                if not prepared.is_file():
                    for folder in ("inputs", "files"):
                        target = directory / folder / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(original, target)
                else:
                    working = directory / "files" / name
                    if working.is_symlink() or not working.resolve().is_relative_to(directory / "files") or digest(working.read_bytes()) != item["sha256"]:
                        raise ValueError("The isolated engine input changed. Create a new run.")
                (directory / "translated" / name).parent.mkdir(parents=True, exist_ok=True)
            atomic_json(prepared, {"ready": True})
            batch_state = None
            from .batches import batch_root, read_document
            batch_directory = batch_root(directory, plan)
            batch_path = batch_directory / "log/batch_state.json"
            if resume and plan["mode"] == "batch" and batch_path.exists():
                batch_state = read_document(batch_directory, 'batch_state.json').get("status")
                if batch_state not in {"queued", "submitted", "partially_submitted", "fetched"}:
                    batch_state = None
            if resume and plan["mode"] == "batch":
                from .batches import entries, recovery_hashes
                if batch_state is None and (plan.get('batch_link') or entries(batch_directory)):
                    raise ValueError("This batch has saved provider history but no resumable state. Prepare recovery from Batch history; new work was not submitted.")
                recovery = job.get("batch_recovery")
                if plan.get('batch_link') and not recovery:
                    raise ValueError('Prepare this linked queue in Batch history before resuming.')
                if recovery and (recovery_hashes(batch_directory) != recovery["hashes"] or batch_state != recovery["state"]):
                    raise ValueError("The batch changed after recovery was prepared. Prepare it again in Batch history.")
                job.pop("batch_recovery", None)
            files = plan["selected"] if plan["mode"] in {"batch", "estimate", "speakers"} else [name for name in plan["selected"] if name not in job["completed"]]
            atomic_json(directory / "attempt.json", {"files": files, "resume": resume, "batch_resume_state": batch_state})
            if not files:
                with self.lock:
                    job.update(status="complete", message="All selected files were already completed.")
                    job["outputs"] = {path.relative_to(directory / "translated").as_posix(): digest(path.read_bytes())
                                      for path in (directory / "translated").rglob("*") if path.is_file() and not path.is_symlink()}
                    self.save(job)
                return
            env = {key: value for key, value in os.environ.items() if key in {
                "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"
            }}
            if plan["mode"] in {"estimate", "offline"}:
                env.update({key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in plan["settings"].items()})
                env.update(key="local-run-no-credential", API_KEY_OPTIONAL="true", DAZEDTL_TEST_OFFLINE="1")
            else:
                runtime = SettingsStore(self.workspace).runtime(plan["settings"], plan["key_name"])
                if runtime["api"] != plan["settings"]["api"]:
                    raise ValueError("The saved credential's endpoint changed. Restore the original route before resuming.")
                env.update(runtime)
            env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHON_DOTENV_DISABLED="1", PYTHONNOUSERSITE="1")
            if os.getenv('DAZEDTL_TEST_OFFLINE') == '1':
                env['DAZEDTL_TEST_OFFLINE'] = '1'
            with (directory / "log/startup.txt").open("a", encoding="utf-8") as error_log:
                process = subprocess.Popen([sys.executable, "-u", str(Path(__file__).with_name("manual_worker.py")), str(directory)],
                                           cwd=directory, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=error_log,
                                           text=True, encoding="utf-8", bufsize=1, start_new_session=os.name != "nt")
                with self.lock:
                    self.process = process
                    if self.stopping.is_set():
                        self._send({"command": "stop"})
                for line in process.stdout:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    self._event(job, event)
                process.wait()
            with self.lock:
                if job["status"] in {"running", "waiting"}:
                    job.update(status="stopped" if self.stopping.is_set() else "failed", approval=None,
                               message="Run stopped. Saved work is available to resume." if self.stopping.is_set() else "The worker exited before completion. See the run log.")
                if job["status"] == "complete":
                    job["outputs"] = {path.relative_to(directory / "translated").as_posix(): digest(path.read_bytes())
                                      for path in (directory / "translated").rglob("*") if path.is_file() and not path.is_symlink()}
                self.save(job)
        except Exception as exc:
            with self.lock:
                job.update(status="stopped" if isinstance(exc, InterruptedError) or self.stopping.is_set() else "failed", approval=None,
                           message=str(exc) if isinstance(exc, (ValueError, InterruptedError)) else f"{type(exc).__name__}: manual run failed. Saved files were retained.")
                self.save(job)
        finally:
            with self.lock:
                self.process = None
                self.active = ""

    def _event(self, job, event):
        with self.lock:
            from util.translation_task import _strip_ansi
            kind, args = event.get("event"), event.get("args", [])
            args = [_strip_ansi(value) if isinstance(value, str) else value for value in args]
            if kind == "log":
                job["log"] = (job["log"] + [str(args[0])[:4000]])[-40:]
            elif kind == "status":
                job["message"] = str(args[0])
            elif kind == "progress":
                job["progress"] = {"current": args[0], "total": args[1], "file": args[2]}
                if job["mode"] in {"translate", "offline"} or job["phase"] == "consume":
                    if args[2] not in job["errors"] and (self.folder(job["id"]) / "translated" / args[2]).is_file():
                        job["completed"] = sorted(set(job["completed"]) | {args[2]})
            elif kind == "item_progress":
                job["item_progress"] = {"file": args[0], "current": args[1], "total": args[2]}
            elif kind in {"file_error", "file_mismatch"}:
                job["errors" if kind == "file_error" else "mismatches"][args[0]] = args[1]
            elif kind == "estimate_ready":
                job["estimate"] = args[0]
            elif kind == "batch_phase":
                job["phase"] = args[0]
                job["batch_detail"] = args[1]
                if args[0] == "submit":
                    job.update(status="waiting", approval={"token": uuid.uuid4().hex, "kind": "batch", "detail": args[1]})
            elif kind == "speaker_confirmation":
                job.update(status="waiting", approval={"token": uuid.uuid4().hex, "kind": "speakers", "detail": args[0]})
            elif kind == "finished":
                job.update(status="stopped" if self.stopping.is_set() else "canceled" if job["phase"] == "canceled" else "complete" if args[0] else "failed",
                           approval=None, message=str(args[1]))
            if self.stopping.is_set() and kind in {"speaker_confirmation", "batch_phase"}:
                self._send({"command": "stop"})
            self.save(job)

    def _send(self, message):
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.write(json.dumps(message) + "\n")
                self.process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

    def answer(self, identity, token, approved):
        with self.lock:
            self.folder(identity)
            job = self.jobs[identity]
            prompt = job.get("approval")
            if not prompt or prompt["token"] != token or identity != self.active or type(approved) is not bool or self.stopping.is_set():
                raise ValueError("This approval is no longer pending. Refresh the run before continuing.")
            self._send({"command": prompt["kind"], "approved": approved})
            job.update(status="running", approval=None, message="Continuing the saved run." if approved else "Canceling this step.")
            self.save(job)
            return json.loads(json.dumps(job))

    def stop(self, identity):
        with self.lock:
            self.folder(identity)
            if identity == self.active and self.running():
                self.stopping.set()
                self._send({"command": "stop"})
                self.jobs[identity].update(approval=None, message="Stopping the local worker. Submitted provider batches remain available to resume.")
                self.save(self.jobs[identity])
            return json.loads(json.dumps(self.jobs[identity]))

    def resume(self, identity):
        with self.lock:
            self.folder(identity)
            if self.running():
                raise ValueError("A manual run is already active.")
            job = self.jobs[identity]
            if job["status"] not in {"failed", "stopped", "interrupted", "canceled"}:
                raise ValueError("This run does not need recovery.")
            if job["mode"] in {"translate", "batch", "speakers"} and not self.allow_providers:
                raise ValueError("Provider execution is disabled in this session.")
            if job.get('batch_root'):
                raise ValueError('Prepare this linked queue in Batch history before resuming.')
            self._launch(job, True)
            return json.loads(json.dumps(job))

    def resume_batch(self, identity, recovery):
        with self.lock:
            self.folder(identity)
            if self.running() or not self.allow_providers:
                raise ValueError("Finish the active run and enable provider execution before resuming.")
            job = self.jobs[identity]
            if job['mode'] != 'batch' or job['status'] in {'running', 'waiting'}:
                raise ValueError('This saved run cannot consume batch results now.')
            job['batch_recovery'] = recovery
            self._launch(job, True)
            return json.loads(json.dumps(job))

    def log(self, identity):
        path = self.folder(identity) / "log/engine.txt"
        if not path.is_file():
            return ""
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 32000))
            return stream.read().decode("utf-8", errors="replace")

    def export(self, identity):
        with self.lock:
            folder = self.folder(identity)
            job = self.jobs[identity]
            if job["status"] != "complete" or not job["outputs"] or self.running():
                raise ValueError("Complete the run before exporting translated files.")
            for name, expected in job["outputs"].items():
                path = folder / "translated" / name
                if path.is_symlink() or digest(path.read_bytes()) != expected:
                    raise ValueError("An output changed after completion; export was stopped.")
            target = self.root / "exports" / uuid.uuid4().hex
            for name in job["outputs"]:
                destination = target / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(folder / "translated" / name, destination)
            context = target / ".dazedtl"
            shutil.copytree(folder / "game/.dazedtl", context)
            atomic_json(target / "dazedtl-run.json", {"job": identity, "engine": job["engine"], "mode": job["mode"], "files": sorted(job["outputs"])})
            job["exports"].append(str(target))
            self.save(job)
            return {"path": str(target), "files": len(job["outputs"])}

    def close(self):
        if self.active:
            self.stop(self.active)
        if self.worker:
            self.worker.join(timeout=5)
        with self.lock:
            process = self.process
            if process and process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                else:
                    os.killpg(process.pid, signal.SIGTERM)
        if self.worker:
            self.worker.join(timeout=3)
