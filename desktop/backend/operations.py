"""Durable, single-operation workers for the guided desktop tools."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import uuid

from .project import atomic_json, digest
from .manual import timestamp


class Operations:
    def __init__(self, workspace, lock):
        self.root = Path(workspace) / "operations"
        self.lock = lock
        self.jobs = {}
        self.worker = None
        self.process = None
        self.active = ""
        self.stopping = threading.Event()
        for path in self.root.glob("*/job.json"):
            job = json.loads(path.read_text(encoding="utf-8"))
            if job["status"] == "running":
                job.update(status="interrupted", message="The application closed during this action. Review its log and destination before running it again.")
                atomic_json(path, job)
            self.jobs[job["id"]] = job

    def running(self):
        return bool(self.worker and self.worker.is_alive())

    def save(self, job):
        job["updated"] = timestamp()
        atomic_json(self.root / job["id"] / "job.json", job)

    def start(self, plan):
        with self.lock:
            if self.running():
                raise ValueError("Wait for the current tool action to finish.")
            identity = uuid.uuid4().hex
            directory = self.root / identity
            directory.mkdir(parents=True)
            atomic_json(directory / "plan.json", plan)
            job = {"id": identity, "created": timestamp(), "project_id": plan["project_id"], "action": plan["action"],
                   "label": plan["label"], "status": "running", "message": "Starting…", "log": [], "result": None,
                   "plan_hash": digest((directory / "plan.json").read_bytes())}
            self.jobs[identity] = job
            self.save(job)
            self.active = identity
            self.stopping.clear()
            self.worker = threading.Thread(target=self._run, args=(identity,), daemon=False)
            self.worker.start()
            return json.loads(json.dumps(job))

    def _run(self, identity):
        job = self.jobs[identity]
        directory = self.root / identity
        try:
            plan = directory / "plan.json"
            if plan.is_symlink() or digest(plan.read_bytes()) != job["plan_hash"]:
                raise ValueError("The saved action changed. Preview it again.")
            environment = {key: value for key, value in os.environ.items() if key in {
                "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH",
                "LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)", "HOME", "USERPROFILE",
                "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "GIT_ATTR_NOSYSTEM",
            }}
            environment.update(DAZEDTL_DESKTOP_WORKSPACE=str(self.root.parent), PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONNOUSERSITE="1", PYTHON_DOTENV_DISABLED="1")
            if os.getenv('DAZEDTL_TEST_OFFLINE') == '1':
                environment['DAZEDTL_TEST_OFFLINE'] = '1'
            with (directory / "worker.log").open("a", encoding="utf-8") as errors:
                process = subprocess.Popen([sys.executable, "-u", str(Path(__file__).with_name("workflow_worker.py")), str(plan)],
                                           cwd=directory, env=environment, stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=errors,
                                           encoding="utf-8", text=True, bufsize=1, start_new_session=os.name != "nt")
                with self.lock:
                    self.process = process
                    if self.stopping.is_set():
                        self._request_stop()
                for line in process.stdout:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    with self.lock:
                        if event.get("event") == "log":
                            job["log"] = (job["log"] + [str(event["message"])[:4000]])[-80:]
                            job["message"] = str(event["message"])[:1000]
                        elif event.get("event") == "finished":
                            job.update(status=event["status"], message=event["message"], result=event.get("result"))
                        self.save(job)
                process.wait()
            with self.lock:
                if job["status"] == "running":
                    job.update(status="interrupted", message="The worker exited before completion. Review the destination before retrying.")
                self.save(job)
        except Exception as exc:
            with self.lock:
                job.update(status="failed", message=str(exc) if isinstance(exc, ValueError) else f"{type(exc).__name__}: tool action failed.")
                self.save(job)
        finally:
            with self.lock:
                self.active = ""
                self.process = None

    def _request_stop(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.write("stop\n")
                self.process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

    def stop(self, identity):
        with self.lock:
            if identity != self.active or not self.running():
                raise ValueError("This tool action is no longer running.")
            self.stopping.set()
            self._request_stop()
            self.jobs[identity]["message"] = "Stopping at the next safe boundary. Completed writes are retained."
            self.save(self.jobs[identity])
            return self.jobs[identity]

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
