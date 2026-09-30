"""Isolated adapter for the same task that drives the Qt translation tab."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PROTOCOL = sys.stdout


def main():
    root = Path(sys.argv[1]).resolve()
    attempt = json.loads((root / "attempt.json").read_text(encoding="utf-8"))
    (root / "log").mkdir(exist_ok=True)
    log = (root / "log/engine.txt").open("a", encoding="utf-8", buffering=1)
    output_lock = threading.Lock()
    secrets = [value for key, value in os.environ.items() if key == "key" and value]
    class RedactedLog:
        def write(self, value):
            for secret in secrets:
                value = value.replace(secret, "[redacted]")
            return log.write(value)
        def flush(self):
            log.flush()
        def isatty(self):
            return False
    sys.stdout = sys.stderr = RedactedLog()
    def emit(event, *args):
        line = json.dumps({"event": event, "args": args}, ensure_ascii=False)
        for value in secrets:
            line = line.replace(value, "[redacted]")
        with output_lock:
            PROTOCOL.write(line + "\n")
            PROTOCOL.flush()
    try:
        from desktop.backend.manual_environment import prepare
        plan = prepare(root)
        from util.translation_task import TranslationTask, translation_module
        task = TranslationTask(root, translation_module(plan["engine"]), code_root=ROOT,
                               runner_script=Path(__file__).with_name("manual_file_worker.py"),
                               estimate_only=plan["mode"] == "estimate", parse_speakers=plan["mode"] == "speakers",
                               batch_mode=plan["mode"] == "batch", selected_files=attempt["files"],
                               batch_resume_state=attempt.get("batch_resume_state"),
                               runtime_profile=plan.get("runtime_profile"), resume_cached=attempt["resume"],
                               preserve_batch_queue=bool(plan.get('batch_link')))
        last_progress = [0.0]
        for name in ("log", "progress", "file_error", "file_mismatch", "status", "batch_phase", "estimate_ready", "speaker_confirmation"):
            getattr(task, name + "_signal").connect(lambda *args, event=name: emit(event, *args))
        def finished(success, message):
            if task.estimate_summary:
                emit("estimate_ready", task.estimate_summary)
            emit("finished", success, message)
        task.finished_signal.connect(finished)
        def progress(*args):
            current = time.monotonic()
            if current - last_progress[0] >= .1 or args[1] == args[2]:
                emit("item_progress", *args)
                last_progress[0] = current
        task.item_progress_signal.connect(progress)
        def commands():
            try:
                for line in sys.stdin:
                    message = json.loads(line)
                    command = message.get("command")
                    if command == "stop":
                        task.stop()
                    elif command == "batch":
                        task.set_batch_submit_response(message.get("approved") is True)
                    elif command == "speakers":
                        task.set_speaker_translation_response(message.get("approved") is True)
            finally:
                task.stop()
        threading.Thread(target=commands, daemon=True).start()
        task.run()
        return 0
    except Exception as exc:
        import traceback
        traceback.print_exc()
        emit("finished", False, f"{type(exc).__name__}: the engine could not finish. See the run log.")
        return 1
    finally:
        sys.stdout = PROTOCOL
        # Daemon control thread can still log during interpreter shutdown.


if __name__ == "__main__":
    raise SystemExit(main())
