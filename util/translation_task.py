"""Qt-free translation task shared by the desktop and legacy Qt interfaces."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import redirect_stdout
from importlib import import_module
from pathlib import Path

from dotenv import load_dotenv
from util.rpgmaker_files import mvmz_file_kind


from util.signals import TaskSignal


def _strip_ansi(text):
    if not isinstance(text, str) or not text:
        return text
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)

def _mismatch_summary(count):
    count = max(0, int(count or 0))
    noun = "mismatch" if count == 1 else "mismatches"
    return f"{count} validation {noun}"

def _is_nontranslatable_mvmz_file(filename) -> bool:
    """Skip any filename without an MV/MZ parser, including plugin databases."""
    return mvmz_file_kind(filename) is None

def _format_estimated_cost(value) -> str:
    """Show useful precision for small runs without noisy large totals."""
    amount = float(value or 0)
    return f"${amount:.4f}" if abs(amount) < 1 else f"${amount:.2f}"

def _estimate_cost_comparison(input_tokens, output_tokens):
    from util.translation import estimateCostComparison

    return estimateCostComparison(input_tokens, output_tokens)

def _result_token_usage(result):
    """Extract one subprocess TOTAL result for aggregate estimate reporting."""
    if isinstance(result, tuple) and len(result) >= 3:
        result = result[2]
    text = _strip_ansi(str(result or ""))
    match = re.search(
        r"\[Input:\s*(?P<input>\d+)\].*?\[Output:\s*(?P<output>\d+)\]",
        text,
    )
    if not match:
        return None
    return int(match.group("input")), int(match.group("output"))

def _format_estimate_total(comparison) -> str:
    comparison = comparison or {}
    token_text = (
        f"[Input: {int(comparison.get('input_tokens', 0) or 0)}]"
        f"[Output: {int(comparison.get('output_tokens', 0) or 0)}]"
    )
    thinking = " + thinking" if comparison.get("unestimated_thinking_tokens") else ""
    live = _format_estimated_cost(comparison.get("live_cost")) + thinking
    if comparison.get("uses_prompt_cache"):
        cached = _format_estimated_cost(
            comparison.get("batch_cached_cost")
        ) + thinking
        worst = _format_estimated_cost(
            comparison.get("batch_nocache_cost")
        ) + thinking
        return (
            f"TOTAL estimate: {token_text}[Batch + cache: {cached}]"
            f"[Batch worst-case: {worst}][Live: {live}]"
        )
    if comparison.get("batch_supported"):
        batch = _format_estimated_cost(comparison.get("batch_cost")) + thinking
        return f"TOTAL estimate: {token_text}[Batch: {batch}][Live: {live}]"
    return f"TOTAL estimate: {token_text}[Live: {live}][Batch: unavailable]"

def _should_prepare_speakers_automatically(
    module_name,
    *,
    estimate_only=False,
    parse_speakers=False,
    batch_mode=False,
    batch_resume_state=None,
) -> bool:
    """Decide whether translation should resolve speakers before file work.

    WolfDawn always auto-preflights on a fresh run. RPG Maker normally relies on
    Workflow "Collect names", but batch collect/consume cannot live-translate
    speakers - unresolved FIRSTLINESPEAKERS (and other nameplates) would stay
    Japanese while dialogue is batched. Fresh RPG Maker batches therefore run
    the same unresolved-speaker preflight.
    """
    name = str(module_name or "").casefold()
    if estimate_only or parse_speakers or (batch_mode and batch_resume_state):
        return False
    if "wolfdawn" in name:
        return True
    if batch_mode and name == "rpg maker mv/mz":
        return True
    return False

TRANSLATION_MODULE_SPECS = (
    ("RPG Maker MV/MZ", (".json",), "modules.rpgmakermvmz", "handleMVMZ"),
    ("CSV", (".csv",), "modules.csv", "handleCSV"),
    ("Tyrano", (".ks",), "modules.tyrano", "handleTyrano"),
    ("Kirikiri", (".ks",), "modules.kirikiri", "handleKirikiri"),
    ("JSON", (".json",), "modules.json", "handleJSON"),
    ("Lune", (".l",), "modules.lune", "handleLune"),
    ("Yuris", (".json",), "modules.yuris", "handleYuris"),
    ("NScript", (".nscript",), "modules.nscript", "handleOnscripter"),
    ("Wolf RPG (WolfDawn)", (".json",), "modules.wolfdawn", "handleWolfDawn"),
    ("Wolf RPG", (".json",), "modules.wolf", "handleWOLF"),
    ("Wolf RPG 2", (".txt",), "modules.wolf2", "handleWOLF2"),
    ("Regex", (".txt", ".json", ".script", ".csv"), "modules.regex", "handleRegex"),
    ("Text", (".txt", ".srt"), "modules.text", "handleText"),
    ("RenPy", (".rpy",), "modules.renpy", "handleRenpy"),
    ("Unity", (".unity",), "modules.unity", "handleUnity"),
    # The strings the semi-manual image workflow exported. Declared by whole
    # filename rather than ".json" so it never offers up a folder of RPG Maker
    # data - the match below is endswith, so both forms work here.
    ("Image Text", ("image_text.json",), "modules.imagetext", "handleImageText"),
    ("RPG Maker Plugin", (".js",), "modules.rpgmakerplugin", "handlePlugin"),
    ("Aquedi4 Prepared JSON", (".json",), "modules.aquedi4", "handleAquedi4"),
    ("SRPG Studio", (".json",), "modules.srpg", "handleSRPG"),
)

def _lazy_module_handler(module_name, handler_name):
    """Return a handler that imports its engine only when translation starts."""

    def run(*args, **kwargs):
        module = import_module(module_name)
        return getattr(module, handler_name)(*args, **kwargs)

    return run


def translation_module(name):
    """Resolve exactly one registered engine without importing its SDKs yet."""
    for label, extensions, module, handler in TRANSLATION_MODULE_SPECS:
        if label == name:
            return label, extensions, _lazy_module_handler(module, handler)
    raise ValueError(f"Unknown translation engine: {name}")


class TranslationTaskCore:
    """Shared translation orchestration; adapters supply the execution thread.

    Engine modules use process-wide state. Run one task per dedicated process
    outside Qt, and never run this directly in the desktop RPC service.
    """

    # Soft validation failure: original kept for bad chunks; run can still succeed.

    def initialize(self, project_root, module_info, estimate_only=False, selected_files=None,
                 parse_speakers=False, batch_mode=False, batch_resume_state=None,
                 batch_workflow_return=None, *, code_root=None, runner_script=None,
                 runtime_profile=None, resume_cached=False, preserve_batch_queue=False):
        self.project_root = Path(project_root)
        self.code_root = Path(code_root) if code_root is not None else self.project_root
        self.runner_script = Path(runner_script) if runner_script is not None else self.code_root / "util/subprocess_runner.py"
        self.runtime_profile_override = runtime_profile
        self.resume_cached = bool(resume_cached)
        self.preserve_batch_queue = bool(preserve_batch_queue)
        self.module_info = module_info  # [name, extensions, handler_function]
        self.estimate_only = estimate_only
        self.selected_files = selected_files  # List of files to process
        # Whether we should run in speaker-parse mode (special-case for MV/MZ)
        self.parse_speakers = parse_speakers
        self.batch_mode = batch_mode
        self.batch_resume_state = batch_resume_state
        self.batch_workflow_return = (
            dict(batch_workflow_return)
            if isinstance(batch_workflow_return, dict)
            else None
        )
        self.batch_runtime_profile = None
        self._batch_submit_event = threading.Event()
        self._batch_submit_approved = False
        self._batch_pending_estimate = None
        self.estimate_summary = None
        self._speaker_confirm_event = threading.Event()
        self._speaker_translation_approved = False
        self._reported_unsupported_mvmz_files = set()
        self.should_stop = False
        self.mutex = threading.RLock()  # For thread safety
        self.executor = None  # Store reference to executor for proper shutdown
        self.running_processes = []  # Track running processes for termination

    def set_batch_submit_response(self, approved):
        """Called from the UI thread after the submit-batch confirmation dialog."""
        with self.mutex:
            self._batch_submit_approved = bool(approved) and not self.should_stop
            self._batch_submit_event.set()

    def set_speaker_translation_response(self, approved):
        """Resume a speaker preflight after the UI confirms or cancels it."""
        with self.mutex:
            self._speaker_translation_approved = bool(approved) and not self.should_stop
            self._speaker_confirm_event.set()

    def _wait_speaker_translation(self, speakers, estimate=None):
        with self.mutex:
            if self.should_stop:
                return False
            self._speaker_translation_approved = False
            self._speaker_confirm_event.clear()
        payload = dict(estimate or {})
        payload["speakers"] = list(speakers)
        self.speaker_confirmation_signal.emit(payload)
        self._speaker_confirm_event.wait()
        return self._speaker_translation_approved and not self.should_stop

    def _report_unsupported_mvmz_file(self, filename):
        """Report an unsupported MV/MZ database once per run."""
        normalized = Path(str(filename)).name.casefold()
        if normalized in self._reported_unsupported_mvmz_files:
            return
        self._reported_unsupported_mvmz_files.add(normalized)
        self.emit_log(
            f"⏭ Skipping {filename}: this RPG Maker data file has no "
            "supported translatable fields."
        )
        # The existing UI renders "Not Supported" as an amber warning rather
        # than a failed file. The worker still completes the overall run.
        self.file_error_signal.emit(filename, f"{filename} Not Supported")

    @staticmethod
    def _estimate_grouped_speakers(speakers, history, config, model):
        """Estimate grouped speaker requests locally without calling a model API."""
        from util.translation import (
            countTokens,
            createContext,
            getPricingConfig,
            isClaudeNative,
        )

        names = [str(name).strip() for name in speakers if str(name).strip()]
        batch_size = max(1, int(getattr(config, "batchSize", 1) or 1))
        max_history = max(1, int(getattr(config, "maxHistory", 10) or 10))
        model_name = str(model or getattr(config, "model", "") or "Unknown")
        pricing = getPricingConfig(model_name)
        input_rate = float(pricing["inputAPICost"]) / 1_000_000
        output_rate = float(pricing["outputAPICost"]) / 1_000_000
        native_claude = isClaudeNative(model_name)

        input_tokens = 0
        output_tokens = 0
        estimated_cost = 0.0
        seen_batch_sizes = set()
        current_history = history

        for offset in range(0, len(names), batch_size):
            name_batch = names[offset:offset + batch_size]
            request_payload = json.dumps(
                {f"Line{index + 1}": value for index, value in enumerate(name_batch)},
                indent=4,
                ensure_ascii=False,
            )
            static_system, vocab_text, user = createContext(
                config, request_payload, "json", current_history
            )
            request_tokens = countTokens(
                static_system + vocab_text, user, current_history
            )
            request_input = max(0, int(request_tokens[0]))
            request_output = max(0, int(request_tokens[1]))
            input_tokens += request_input
            output_tokens += request_output

            if native_claude:
                static_tokens = countTokens(static_system, "", "")[0]
                regular_tokens = max(0, request_input - static_tokens)
                # Match the translator's conservative cold-cache estimate: the
                # first request for each output-schema size writes the cached
                # prompt; repeated sizes receive the cache-read discount.
                cache_multiplier = 2.0 if len(name_batch) not in seen_batch_sizes else 0.10
                estimated_cost += (
                    static_tokens * input_rate * cache_multiplier
                    + regular_tokens * input_rate
                    + request_output * output_rate
                )
                seen_batch_sizes.add(len(name_batch))
            else:
                estimated_cost += (
                    request_input * input_rate + request_output * output_rate
                )
            current_history = name_batch[-max_history:]

        return {
            "model": model_name,
            "request_count": (len(names) + batch_size - 1) // batch_size,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost": estimated_cost,
            "cold_cache": native_claude,
        }

    def _wait_batch_submit(self, estimate):
        with self.mutex:
            self._batch_pending_estimate = estimate
            self._batch_submit_approved = False
            if not self.should_stop:
                self._batch_submit_event.clear()
            else:
                self._batch_submit_event.set()
        if not self.should_stop:
            self.batch_phase_signal.emit("submit", estimate)
        self._batch_submit_event.wait()
        approved = self._batch_submit_approved and not self.should_stop
        if not approved and not self.preserve_batch_queue:
            from util.translation import clearBatchFiles
            clearBatchFiles(strict=True)
        return approved

    def _emit_batch_phase(self, phase, payload=None):
        self.batch_phase_signal.emit(phase, payload)

    def _emit_batch_output(self, fn, *args, **kwargs):
        """Run a batch helper that prints status lines; forward them to the log."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = fn(*args, **kwargs)
        for line in buf.getvalue().splitlines():
            if line.strip():
                self.emit_log(line)
        return result

    def _run_batch_poll_fetch(self):
        """Submit, poll, and fetch; return False on provider terminal failure."""
        from util.translation import (
            submitTranslationBatches,
            fetchTranslationBatches,
            failedTranslationBatchStatuses,
            formatTranslationBatchFailures,
            _read_batch_file,
            BATCH_STATE_FILE,
            _batch_file_lock,
        )

        with _batch_file_lock():
            state = _read_batch_file(BATCH_STATE_FILE)
        if not state.get("batches") or (
            state.get("status") == "partially_submitted" and not state.get("sequential_token_limit")
        ):
            est = self._batch_pending_estimate
            file_set = list(self.selected_files or [])
            if not self._emit_batch_output(
                submitTranslationBatches,
                file_set=file_set,
                cost_estimate=est,
            ):
                return 0, 0

        poll = int(os.getenv("batchPollInterval", "60") or 60)
        self._emit_batch_phase("polling")
        self.emit_log(
            f"[BATCH] polling every {poll}s (stop is safe - resume later with Batch Translate mode)..."
        )
        from util.translation import checkTranslationBatchStatuses
        while True:
            if self.should_stop:
                self.emit_log("[BATCH] Stopped while polling. Batch keeps processing - resume later.")
                return None
            buf = io.StringIO()
            with redirect_stdout(buf):
                ended, statuses = checkTranslationBatchStatuses(print_status=True)
            for line in buf.getvalue().splitlines():
                if line.strip():
                    self.emit_log(line)
            if statuses:
                self._emit_batch_phase("poll_status", statuses)
            if ended:
                failures = failedTranslationBatchStatuses(statuses)
                if failures:
                    detail = formatTranslationBatchFailures(failures)
                    message = (
                        "Provider batch failed before usable results were available. "
                        "The local request queue was preserved and the consume/write "
                        "pass was not started."
                    )
                    if detail:
                        message = f"{message} {detail}"
                    self.emit_log(f"❌ [BATCH] {message}")
                    self._emit_batch_phase("failed", {"message": message})
                    return False
                with _batch_file_lock():
                    state = _read_batch_file(BATCH_STATE_FILE)
                if state.get("status") == "partially_submitted":
                    if self.should_stop:
                        return None
                    self.emit_log(
                        "[BATCH] Current provider chunk completed. Submitting the next queued chunk..."
                    )
                    self._emit_batch_output(submitTranslationBatches)
                    continue
                break
            for _ in range(poll * 10):
                if self.should_stop:
                    self.emit_log("[BATCH] Stopped while polling. Batch keeps processing - resume later.")
                    return None
                time.sleep(0.1)

        fetched, errored = self._emit_batch_output(fetchTranslationBatches)
        return fetched, errored

    def stop(self):
        """Stop the translation process."""
        self.mutex.acquire()
        try:
            if self.should_stop:
                # Already stopping, don't log again
                return

            self.should_stop = True
            self._batch_submit_approved = False
            self._batch_submit_event.set()
            self._speaker_translation_approved = False
            self._speaker_confirm_event.set()
            self.emit_log("🛑 Stopping translation worker and canceling pending tasks...")

            # Shutdown the executor if it exists
            if self.executor:
                # For older Python versions compatibility, use shutdown(wait=False)
                # and manually cancel futures
                try:
                    # Try to use cancel_futures parameter (Python 3.9+)
                    self.executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    # Fallback for older Python versions
                    self.executor.shutdown(wait=False)

            # Terminate any running processes
            if self.running_processes:
                self.emit_log("🛑 Terminating running translation processes...")
                for process in self.running_processes:
                    try:
                        if process.poll() is None:  # Process is still running
                            process.terminate()
                            # Give it a moment to terminate gracefully
                            try:
                                process.wait(timeout=2)
                            except subprocess.TimeoutExpired:
                                # Force kill if it doesn't terminate
                                process.kill()
                                process.wait()
                    except Exception as e:
                        self.emit_log(f"⚠️ Warning: Could not terminate process: {e}")
                self.running_processes.clear()
        finally:
            self.mutex.release()

    def emit_log(self, message):
        """Thread-safe log emission.

        Also mirrors into TRANSLATION_RUN_LOG so the LogViewer file-tail shows
        batch/status lines (those never go through translateAI's Input/Output writer).
        """
        self.log_signal.emit(message)
        if isinstance(message, str) and message.startswith("MISMATCH_EVENT:"):
            return
        try:
            run_log = os.getenv("TRANSLATION_RUN_LOG")
            if not run_log or not message:
                return
            text = _strip_ansi(str(message)).rstrip()
            if not text:
                return
            path = Path(run_log)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(text + "\n")
                f.flush()
        except Exception:
            pass

    def emit_progress(self, current, total, filename):
        """Thread-safe progress emission."""
        self.progress_signal.emit(current, total, filename)

    def run_module_in_process(
        self,
        filename,
        estimate_only,
        batch_phase=None,
        file_result_callback=None,
    ):
        """Run a module handler in a separate process for better control."""
        try:
            # Use the external subprocess runner script
            runner_script = self.runner_script
            if not runner_script.exists():
                self.emit_log(f"❌ Subprocess runner script not found: {runner_script}")
                return "Fail"

            # Run the script in a separate process
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'  # Force UTF-8 encoding
            if batch_phase in ("collect", "estimate", "consume"):
                env["BATCH_PHASE"] = batch_phase
                if self.batch_runtime_profile is not None:
                    env["DAZED_BATCH_RUNTIME_PROFILE"] = json.dumps(
                        self.batch_runtime_profile,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                else:
                    env.pop("DAZED_BATCH_RUNTIME_PROFILE", None)
            else:
                env.pop("BATCH_PHASE", None)
                env.pop("DAZED_BATCH_RUNTIME_PROFILE", None)

            multi_file = isinstance(filename, (list, tuple))
            filenames = list(filename) if multi_file else None
            filename_arg = "--files-from-stdin" if multi_file else filename
            if self.should_stop:
                return "Stopped"
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(runner_script),
                    str(self.project_root),
                    self.module_info[0],  # module name
                    filename_arg,
                    str(estimate_only)
                ],
                stdin=subprocess.PIPE if multi_file else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                cwd=str(self.project_root),
                env=env,
                bufsize=1  # Line buffered
            )

            # Track the process for potential termination
            with self.mutex:
                stopped_at_launch = self.should_stop
                if not stopped_at_launch:
                    self.running_processes.append(process)
            if stopped_at_launch:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                return "Stopped"
            if multi_file:
                json.dump(filenames, process.stdin, ensure_ascii=False)
                process.stdin.close()

            # Read output in real-time to capture progress
            stdout_lines = []
            stderr_lines = []

            def read_stdout():
                """Read stdout line by line."""
                for line in iter(process.stdout.readline, ''):
                    if not line:
                        break
                    line = line.strip()
                    if line.startswith('PROGRESS:'):
                        # Parse progress: PROGRESS:filename:current:total
                        try:
                            parts = line.split(':', 3)
                            if len(parts) == 4:
                                _, desc, current, total = parts
                                # Emit with filename included
                                self.item_progress_signal.emit(desc, int(current), int(total))
                        except Exception:
                            pass  # Ignore malformed progress lines
                    elif line.startswith("FILE_RESULT:"):
                        try:
                            payload = json.loads(line[len("FILE_RESULT:"):])
                            if file_result_callback is not None:
                                result = payload.get("result") or "Fail"
                                mismatch_count = int(
                                    payload.get("mismatch_count") or 0
                                )
                                if mismatch_count:
                                    result = (
                                        "VALIDATION_MISMATCH",
                                        "Translation validation failed after all "
                                        "retries; original text was preserved for "
                                        "failed chunks",
                                        result,
                                        mismatch_count,
                                    )
                                file_result_callback(payload["filename"], result)
                        except Exception as exc:
                            stderr_lines.append(
                                f"Invalid multi-file result marker: {exc}"
                            )
                    elif line.startswith("FILE_ERROR:"):
                        try:
                            payload = json.loads(line[len("FILE_ERROR:"):])
                            if file_result_callback is not None:
                                file_result_callback(
                                    payload["filename"],
                                    (
                                        "SUBPROCESS_ERROR",
                                        payload.get("error") or "Unknown error",
                                    ),
                                )
                        except Exception as exc:
                            stderr_lines.append(
                                f"Invalid multi-file error marker: {exc}"
                            )
                    else:
                        stdout_lines.append(line)
                        # Forward each line to the log as it is read, rather than
                        # buffering the whole run and flushing it after the
                        # process exits — a long translation was otherwise a
                        # blank log until it finished. RESULT: is an internal
                        # marker parsed below and is never shown.
                        if line and not line.startswith('RESULT:'):
                            self.emit_log(line)
                process.stdout.close()

            def read_stderr():
                """Read stderr line by line."""
                for line in iter(process.stderr.readline, ''):
                    if not line:
                        break
                    stderr_lines.append(line.strip())
                process.stderr.close()

            # Start reader threads
            stdout_thread = threading.Thread(target=read_stdout, daemon=True)
            stderr_thread = threading.Thread(target=read_stderr, daemon=True)
            stdout_thread.start()
            stderr_thread.start()

            # Wait for process completion
            process.wait()

            # Wait for reader threads to finish
            stdout_thread.join(timeout=1.0)
            stderr_thread.join(timeout=1.0)

            # Combine output
            stdout = '\n'.join(stdout_lines)
            stderr = '\n'.join(stderr_lines)

            # Remove from tracking
            if process in self.running_processes:
                self.running_processes.remove(process)

            # Check if process was terminated by stop signal
            if self.should_stop:
                return "Stopped"

            stdout_lines_clean = stdout.strip().split('\n')
            mismatch_count = sum(
                line.startswith("MISMATCH_EVENT:")
                for line in stdout_lines_clean
            )

            # stdout was already forwarded to the log line by line as it was
            # read (see read_stdout); it is not re-emitted here, only parsed for
            # the RESULT/MISMATCH markers below.

            # Parse result
            if process.returncode == 0:
                result_text = "Success"
                for line in stdout_lines_clean:
                    if line.startswith('RESULT:'):
                        parsed = line[7:]  # Remove 'RESULT:' prefix
                        try:
                            result_text = parsed
                        except UnicodeError:
                            result_text = parsed.encode('ascii', 'ignore').decode('ascii')
                        break
                if mismatch_count:
                    # Soft failure: bad chunks keep source text, valid chunks are
                    # written. Do not fail the whole multi-file run for this.
                    return (
                        "VALIDATION_MISMATCH",
                        "Translation validation failed after all retries; "
                        "original text was preserved for failed chunks",
                        result_text,
                        mismatch_count,
                    )
                return result_text
            else:
                # Extract error message from stderr
                error_msg = stderr.strip() if stderr.strip() else "Unknown error"
                # Handle potential Unicode errors in error messages
                try:
                    clean_error = error_msg.encode('ascii', 'ignore').decode('ascii')
                except:
                    clean_error = "Unicode encoding error in process output"

                # Check if stderr contains the actual exception message
                # Format from subprocess_runner.py: "ERROR:actual error message"
                actual_error = clean_error
                for line in clean_error.split('\n'):
                    if line.startswith('ERROR:'):
                        actual_error = line[6:]  # Remove 'ERROR:' prefix
                        break
                    # Check for exception lines in traceback
                    if 'NameError:' in line or 'Error:' in line:
                        # Extract just the error message part
                        if ':' in line:
                            actual_error = line.split(':', 1)[1].strip()
                            break

                self.emit_log(f"❌ Process error: {actual_error}")
                # Return the actual error so it can be used to determine if file is unsupported
                return ("SUBPROCESS_ERROR", actual_error)

        except Exception as e:
            self.emit_log(f"❌ Failed to run module process: {str(e)}")
            return "Fail"

    def _prepare_mvmz_speakers(self, matching_files, *, emit_progress=False):
        """Scan selected RPG Maker files, then resolve all new speakers together."""
        try:
            import modules.rpgmakermvmz as mvmz
            mvmz.refreshRuntimeConfig()
            if self.batch_runtime_profile is not None:
                from util.runtime_profile import apply_batch_runtime_profile

                apply_batch_runtime_profile(mvmz, self.batch_runtime_profile)
        except Exception as exc:
            self.emit_log(f"❌ Could not start speaker preflight: {exc}")
            return False

        mvmz.resetSpeakerState()
        mvmz.setSpeakerParseMode(True)
        total_files = len(matching_files)
        completed = 0
        scan_failures = []
        try:
            self.status_signal.emit("Scanning speakers…")
            self.emit_log(
                f"🔎 Scanning {total_files} file(s) for unresolved speakers "
                "without making API calls…"
            )
            for filename in matching_files:
                if self.should_stop:
                    return False
                if _is_nontranslatable_mvmz_file(filename):
                    self._report_unsupported_mvmz_file(filename)
                    completed += 1
                    self.status_signal.emit(
                        f"Scanning speakers… {completed}/{total_files}"
                    )
                    if emit_progress:
                        self.emit_progress(completed, total_files, filename)
                    continue
                try:
                    mvmz.handleMVMZ(filename, False)
                except Exception as exc:
                    scan_failures.append(filename)
                    tb_line = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
                    self.emit_log(
                        f"❌ Error scanning speakers in {filename}: {exc} | Line: {tb_line}"
                    )
                    self.file_error_signal.emit(filename, str(exc))
                completed += 1
                self.status_signal.emit(
                    f"Scanning speakers… {completed}/{total_files}"
                )
                if emit_progress:
                    self.emit_progress(completed, total_files, filename)

            if scan_failures:
                self.emit_log(
                    f"❌ Speaker scan failed for {len(scan_failures)}/{total_files} "
                    "file(s). No speaker translations were submitted."
                )
                return False

            skipped_count = sum(
                _is_nontranslatable_mvmz_file(filename)
                for filename in matching_files
            )
            scan_summary = f"{completed}/{total_files}"
            if skipped_count:
                scan_summary += f"; {skipped_count} unsupported skipped"

            pending = mvmz.pendingSpeakerNames()
            collected_unique = []
            seen_collected = set()
            for name in mvmz.SPEAKER_COLLECTED:
                if not name or name in seen_collected:
                    continue
                seen_collected.add(name)
                collected_unique.append(name)
            covered_count = max(0, len(collected_unique) - len(pending))
            if not pending:
                self.emit_log(
                    f"🔤 Speaker scan complete ({scan_summary}). "
                    f"Detected {len(collected_unique)} unique nameplate(s); "
                    f"all {covered_count} are already covered by the game glossary."
                )
                return True

            self.status_signal.emit(f"Waiting to translate {len(pending)} speakers…")
            self.emit_log(
                f"🔤 Speaker scan complete ({scan_summary}). "
                f"Detected {len(collected_unique)} unique nameplate(s); "
                f"{covered_count} already covered by the glossary; "
                f"{len(pending)} unresolved unique speaker(s). "
                "No speaker API calls have been made."
            )
            from util.skills import ctx
            estimate = self._estimate_grouped_speakers(
                pending, ctx("names.speaker"), mvmz.TRANSLATION_CONFIG, mvmz.MODEL
            )
            self.emit_log(
                f"📊 Speaker estimate: {int(estimate.get('request_count', 0))} grouped request(s), "
                f"{int(estimate.get('input_tokens', 0)):,} input / "
                f"{int(estimate.get('output_tokens', 0)):,} output tokens, approximately "
                f"${float(estimate.get('estimated_cost', 0.0)):.6f}."
            )
            if not self._wait_speaker_translation(pending, estimate):
                self.emit_log(
                    "⏹ Speaker translation canceled. No unresolved speakers were sent, "
                    "and the translation run did not start."
                )
                return False

            self.status_signal.emit(f"Translating {len(pending)} speakers together…")
            self.emit_log(
                f"🔤 Translating {len(pending)} speakers in grouped list batches…"
            )
            before_in, before_out = int(mvmz.TOKENS[0]), int(mvmz.TOKENS[1])
            speakers_saved = mvmz.finalizeSpeakerParse()
            if speakers_saved is False:
                self.emit_log(
                    "❌ Speaker translations could not be validated or saved. "
                    "Check the active game glossary and translation log."
                )
                return False
            delta_in = max(0, int(mvmz.TOKENS[0]) - before_in)
            delta_out = max(0, int(mvmz.TOKENS[1]) - before_out)
            if delta_in or delta_out:
                cost = mvmz.calculateCost(delta_in, delta_out, mvmz.MODEL)
                self.emit_log(
                    f"Speakers: [Input: {delta_in}][Output: {delta_out}]"
                    f"[Cost: ${cost:.4f}] ✓"
                )
            self.emit_log("✅ Speaker translations saved to the game glossary.")
            return True
        finally:
            mvmz.setSpeakerParseMode(False)

    def _prepare_wolf_speakers(self, matching_files):
        """Scan WolfDawn JSON nameplates, then resolve all new speakers together."""
        try:
            import modules.wolfdawn as wolfdawn
            wolfdawn.refreshRuntimeConfig()
        except Exception as exc:
            self.emit_log(f"❌ Could not start WOLF speaker preflight: {exc}")
            return False

        collected = []
        seen = set()
        scan_failures = []
        total_files = len(matching_files)
        self.status_signal.emit("Scanning WOLF speakers…")
        self.emit_log(
            f"🔎 Scanning {total_files} WOLF JSON file(s) for unresolved speakers "
            "without making API calls…"
        )
        for index, filename in enumerate(matching_files, 1):
            if self.should_stop:
                return False
            try:
                path = self.project_root / "files" / filename
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                for speaker in wolfdawn.collectSpeakerNames(data):
                    if speaker not in seen:
                        seen.add(speaker)
                        collected.append(speaker)
            except Exception as exc:
                scan_failures.append(filename)
                self.emit_log(f"❌ Could not scan WOLF speakers in {filename}: {exc}")
                self.file_error_signal.emit(filename, str(exc))
            self.status_signal.emit(
                f"Scanning WOLF speakers… {index}/{total_files}"
            )

        if scan_failures:
            self.emit_log(
                f"❌ WOLF speaker scan failed for {len(scan_failures)}/{total_files} "
                "file(s). No speaker translations were submitted."
            )
            return False

        pending = wolfdawn.pendingSpeakerNames(collected)
        if not pending:
            self.emit_log(
                f"🔤 WOLF speaker scan complete ({total_files}/{total_files}). "
                "Every detected speaker is already in the game glossary."
            )
            return True

        self.status_signal.emit(f"Waiting to translate {len(pending)} speakers…")
        self.emit_log(
            f"🔤 WOLF speaker scan complete. Found {len(pending)} unresolved unique "
            "speaker(s); no speaker API calls have been made."
        )
        from util.skills import ctx
        estimate = self._estimate_grouped_speakers(
            pending, ctx("names.npc"), wolfdawn.TRANSLATION_CONFIG, wolfdawn.MODEL
        )
        self.emit_log(
            f"📊 Speaker estimate: {int(estimate.get('request_count', 0))} grouped request(s), "
            f"{int(estimate.get('input_tokens', 0)):,} input / "
            f"{int(estimate.get('output_tokens', 0)):,} output tokens, approximately "
            f"${float(estimate.get('estimated_cost', 0.0)):.6f}."
        )
        if not self._wait_speaker_translation(pending, estimate):
            self.emit_log(
                "⏹ Speaker translation canceled. No unresolved speakers were sent, "
                "and the translation run did not start."
            )
            return False

        self.status_signal.emit(f"Translating {len(pending)} speakers together…")
        self.emit_log(
            f"🔤 Translating {len(pending)} WOLF speakers in grouped list batches…"
        )
        tokens = wolfdawn.translateSpeakerNames(pending)
        if tokens is False:
            self.emit_log(
                "❌ WOLF speaker translations could not be validated or saved. "
                "The translation run did not start."
            )
            return False
        if tokens[0] or tokens[1]:
            cost = wolfdawn.calculateCost(tokens[0], tokens[1], wolfdawn.MODEL)
            self.emit_log(
                f"Speakers: [Input: {tokens[0]}][Output: {tokens[1]}]"
                f"[Cost: ${cost:.4f}] ✓"
            )
        self.emit_log("✅ Speaker translations saved to the game glossary.")
        return True

    def _run_files(self, matching_files, estimate_only, batch_phase=None):
        """Process matching files; return last cost string or 'Fail'."""
        threads = int(os.getenv("fileThreads", "1"))
        total_cost = "Fail"
        had_failure = False
        module_name_lower = self.module_info[0].lower() if isinstance(self.module_info[0], str) else ""
        is_mvmz = "mv/mz" in module_name_lower

        if self.parse_speakers and is_mvmz:
            prepared = self._prepare_mvmz_speakers(
                matching_files, emit_progress=True
            )
            if not prepared:
                self.should_stop = True
                return "Stopped"
            return "Success"

        completed_count = 0
        total_files = len(matching_files)
        estimate_input_tokens = 0
        estimate_output_tokens = 0
        self._run_had_mismatch = False
        self._run_mismatch_count = 0

        unsupported_files = []
        if is_mvmz:
            unsupported_files = [
                filename
                for filename in matching_files
                if _is_nontranslatable_mvmz_file(filename)
            ]
            matching_files = [
                filename
                for filename in matching_files
                if not _is_nontranslatable_mvmz_file(filename)
            ]

        def _handle_file_result(filename, result):
            nonlocal total_cost, had_failure, completed_count
            nonlocal estimate_input_tokens, estimate_output_tokens
            stopped = False
            if estimate_only:
                usage = _result_token_usage(result)
                if usage is not None:
                    estimate_input_tokens += usage[0]
                    estimate_output_tokens += usage[1]
            try:
                if (
                    isinstance(result, tuple)
                    and len(result) >= 2
                    and result[0] == "VALIDATION_MISMATCH"
                ):
                    message = result[1]
                    cost = result[2] if len(result) > 2 else None
                    mismatch_count = max(
                        1, int(result[3] if len(result) > 3 else 1)
                    )
                    self._run_had_mismatch = True
                    self._run_mismatch_count += mismatch_count
                    self.emit_log(
                        f"⚠ {filename}: {_mismatch_summary(mismatch_count)}; "
                        "original text kept for those chunks."
                    )
                    self.file_mismatch_signal.emit(filename, message)
                    if cost and cost not in ("Fail", "Stopped"):
                        total_cost = cost
                    elif total_cost == "Fail":
                        total_cost = "Success"
                elif isinstance(result, tuple) and len(result) == 2 and result[0] == "SUBPROCESS_ERROR":
                    had_failure = True
                    self.file_error_signal.emit(filename, result[1])
                elif result and result not in ("Fail", "Stopped"):
                    total_cost = result
                elif result == "Stopped":
                    stopped = True
                else:
                    had_failure = True
                    self.emit_log(f"❌ Failed processing {filename}")
                    self.file_error_signal.emit(filename, "Translation failed")
            except Exception as e:
                had_failure = True
                tb_line = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
                self.emit_log(f"❌ Error processing {filename}: {str(e)} | Line: {tb_line}")
                self.file_error_signal.emit(filename, str(e))
            completed_count += 1
            self.emit_progress(completed_count, total_files, filename)
            return stopped

        def _completed_result():
            if had_failure:
                return "Fail"
            if self.should_stop:
                return "Stopped"
            if estimate_only and batch_phase != "estimate":
                comparison = _estimate_cost_comparison(
                    estimate_input_tokens,
                    estimate_output_tokens,
                )
                self.estimate_summary = comparison
                return _format_estimate_total(comparison)
            if estimate_only:
                return total_cost if total_cost != "Fail" else "Success"
            return total_cost

        for filename in unsupported_files:
            self._report_unsupported_mvmz_file(filename)
            completed_count += 1
            self.emit_progress(completed_count, total_files, filename)

        if not matching_files:
            return _completed_result() if estimate_only else "Success"

        # Batch collection and consumption are local, CPU/file-heavy phases.
        # Reuse one imported RPG Maker process for the whole phase instead of
        # paying heavyweight SDK/module startup once per file. Consume remains
        # strictly ordered, preserving glossary harvest semantics.
        if is_mvmz and batch_phase in ("collect", "estimate", "consume"):
            observed = set()

            def _handle_persistent_result(filename, result):
                observed.add(filename)
                _handle_file_result(filename, result)

            worker_result = self.run_module_in_process(
                list(matching_files),
                estimate_only,
                batch_phase,
                file_result_callback=_handle_persistent_result,
            )
            if self.should_stop:
                return "Stopped"
            if (
                isinstance(worker_result, tuple)
                and worker_result
                and worker_result[0] == "SUBPROCESS_ERROR"
            ):
                for filename in matching_files:
                    if filename not in observed:
                        _handle_file_result(filename, worker_result)
            return "Fail" if had_failure else total_cost

        # Pass 2 is always sequential: each file may harvest names into
        # glossary.txt, and later files need those entries on disk. Paid batch
        # keys still use the collect-time freeze, so these writes are safe.
        if batch_phase == "consume":
            self.executor = None
            for filename in matching_files:
                if self.should_stop:
                    break
                result = self.run_module_in_process(
                    filename, estimate_only, batch_phase
                )
                if _handle_file_result(filename, result):
                    break
            return "Fail" if had_failure else total_cost

        # Estimate cache accounting now claims prompt-cache writes under a
        # cross-process lock, so estimation can safely use the configured file
        # concurrency instead of serializing every subprocess.
        max_workers = max(1, threads)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        future_to_filename = {
            self.executor.submit(
                self.run_module_in_process, filename, estimate_only, batch_phase
            ): filename
            for filename in matching_files
        }

        for future in as_completed(future_to_filename):
            if self.should_stop:
                for remaining_future in future_to_filename:
                    if not remaining_future.done():
                        remaining_future.cancel()
                break

            filename = future_to_filename[future]
            # Resolve the future before emitting progress so cost lines from the
            # subprocess are queued ahead of the file-complete progress event.
            try:
                result = future.result()
            except Exception as e:
                had_failure = True
                tb_line = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
                self.emit_log(f"❌ Error processing {filename}: {str(e)} | Line: {tb_line}")
                self.file_error_signal.emit(filename, str(e))
                completed_count += 1
                self.emit_progress(completed_count, total_files, filename)
                continue
            if _handle_file_result(filename, result):
                break

        if self.executor:
            try:
                self.executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                self.executor.shutdown(wait=False)
            self.executor = None

        return _completed_result()

    def run(self):
        """Run the translation process."""
        use_batch_estimate = False
        try:
            load_dotenv(self.project_root / ".env")
            sys.path.insert(0, str(self.code_root))

            from util.translation import clear_cache

            if not self.resume_cached and not (self.batch_mode and self.batch_resume_state):
                clear_cache()

            required_envs = ["api", "key", "model", "language", "timeout", "fileThreads", "threads", "width", "listWidth"]
            missing_envs = [
                env for env in required_envs
                if os.getenv(env) is None or str(os.getenv(env))[:1] == "<"
            ]
            if missing_envs:
                names = ", ".join(missing_envs)
                self.emit_log(f"❌ Missing required environment variable(s): {names}")
                self.emit_log("   Check your .env file (see .env.example).")
                self.finished_signal.emit(False, f"Missing env: {names}")
                return

            if self.estimate_only:
                from util.translation import isBatchSupported

                use_batch_estimate = isBatchSupported()

            if self.batch_mode and self.parse_speakers:
                self.emit_log("❌ Batch Translate does not support Parse Speakers mode.")
                self.finished_signal.emit(False, "Batch + Parse Speakers unsupported")
                return

            if self.batch_mode or use_batch_estimate:
                from util.runtime_profile import (
                    capture_batch_runtime_profile,
                    copy_batch_runtime_profile,
                    is_rpgmaker_mvmz,
                )
                from util.translation import batchRunMetadata

                if self.batch_mode and self.batch_resume_state:
                    saved_profile = batchRunMetadata().get("runtime_profile")
                    if is_rpgmaker_mvmz(self.module_info[0]) and saved_profile is None:
                        self.emit_log(
                            "❌ This RPG Maker batch predates saved runtime profiles. "
                            "Resume was stopped before writing files. Reopen it from the "
                            "guided workflow and confirm the original code profile first."
                        )
                        self.finished_signal.emit(False, "Batch runtime profile missing")
                        return
                    self.batch_runtime_profile = copy_batch_runtime_profile(
                        saved_profile
                    )
                else:
                    self.batch_runtime_profile = (
                        copy_batch_runtime_profile(self.runtime_profile_override)
                        if self.runtime_profile_override is not None
                        else capture_batch_runtime_profile(self.module_info[0], self.code_root)
                    )

            files_dir = self.project_root / "files"
            if not files_dir.exists():
                self.emit_log("❌ Files directory does not exist!")
                self.finished_signal.emit(False, "Files directory missing")
                return

            if self.selected_files:
                matching_files = self.selected_files
            else:
                matching_files = []
                for file_path in files_dir.iterdir():
                    if file_path.is_file() and file_path.name != '.gitkeep':
                        for ext in self.module_info[1]:
                            if file_path.name.endswith(ext):
                                matching_files.append(file_path.name)
                                break

            if not matching_files:
                self.emit_log(f"❌ No files found matching extensions: {', '.join(self.module_info[1])}")
                self.finished_signal.emit(False, "No matching files")
                return

            self.emit_log(f"📁 Found {len(matching_files)} files to process:")
            for filename in matching_files:
                self.emit_log(f"   • {filename}")
            self.emit_log(f"🔧 Using module: {self.module_info[0]}")
            if self.batch_mode:
                self.emit_log("📦 Batch mode: provider Batch API (typically 50% off)")
            else:
                self.emit_log(f"📊 Estimate only: {'Yes' if self.estimate_only else 'No'}")
                if self.estimate_only:
                    self.emit_log(
                        "🔒 Estimate safety: translation generation is disabled and "
                        "translated files will not be written."
                    )
            self.emit_log("")

            total_cost = "Fail"
            batch_no_work = False
            old_cwd = os.getcwd()
            os.chdir(str(self.project_root))

            if self.estimate_only and not use_batch_estimate:
                try:
                    from util.translation import clear_estimate_written_sizes
                    clear_estimate_written_sizes()
                except Exception:
                    pass

            try:
                should_prepare_speakers = _should_prepare_speakers_automatically(
                    self.module_info[0],
                    estimate_only=self.estimate_only,
                    parse_speakers=self.parse_speakers,
                    batch_mode=self.batch_mode,
                    batch_resume_state=self.batch_resume_state,
                )
                if should_prepare_speakers:
                    module_name_lower = str(self.module_info[0] or "").casefold()
                    if "wolfdawn" in module_name_lower:
                        prepared = self._prepare_wolf_speakers(matching_files)
                    else:
                        prepared = self._prepare_mvmz_speakers(matching_files)
                    if not prepared:
                        self.finished_signal.emit(False, "Speaker translation canceled")
                        return

                if self.batch_mode:
                    from util.translation import (
                        batchQueueStaleContextCount,
                        clearBatchFiles,
                        pendingBatchRequests,
                        estimateBatchCost,
                        saveQueuedBatchMetadata,
                    )

                    if self.batch_resume_state == "queued":
                        stale_requests, queued_requests = batchQueueStaleContextCount()
                        if stale_requests:
                            if self.preserve_batch_queue:
                                raise ValueError("The linked queue does not match the saved translation context. Its requests were preserved; restore the original context before resuming.")
                            self.emit_log(
                                f"[BATCH] Glossary or SFX context changed for "
                                f"{stale_requests}/{queued_requests} queued request(s). "
                                "Discarding the stale queue and re-collecting with the "
                                "current translation context."
                            )
                            clearBatchFiles()
                            self.batch_resume_state = None

                    run_consume = True
                    if self.batch_resume_state is None:
                        clearBatchFiles()
                        try:
                            from util.vocab import (
                                freeze_batch_glossary,
                                persist_batch_glossary_freeze_to_state,
                            )

                            freeze_batch_glossary()
                            persist_batch_glossary_freeze_to_state()
                            self.emit_log(
                                "[BATCH] Froze glossary for collect prompts "
                                "(and legacy result rematch if needed)."
                            )
                        except Exception as exc:
                            self.emit_log(
                                f"[BATCH] Could not freeze glossary context: {exc}"
                            )
                        self._emit_batch_phase("collect")
                        self.emit_log("[BATCH] Pass 1/2: collecting requests...")
                        self.emit_log(
                            "[BATCH] Pass 1 queues the main translation requests without "
                            "per-speaker API calls; unresolved speakers were resolved in "
                            "the preflight glossary step when needed."
                        )
                        total_cost = self._run_files(matching_files, False, batch_phase="collect")
                        if self.should_stop:
                            self.finished_signal.emit(False, "Translation stopped")
                            return
                        if total_cost == "Fail":
                            self.emit_log(
                                "[BATCH] Collection failed; submission was blocked so "
                                "no incomplete paid batch can be created."
                            )
                            self.finished_signal.emit(False, "Batch collection failed")
                            return

                        if pendingBatchRequests() == 0:
                            batch_no_work = True
                            self._emit_batch_phase("no_work", {
                                "files": len(matching_files),
                            })
                            self.emit_log(
                                "[BATCH] No eligible untranslated text found. "
                                "No provider batch was submitted."
                            )
                            run_consume = False
                        else:
                            n_requests = pendingBatchRequests()
                            self._emit_batch_phase("collect_done", {
                                "files": len(matching_files),
                                "requests": n_requests,
                            })
                            est = self._emit_batch_output(estimateBatchCost)
                            if est is not None:
                                est = dict(est)
                                est["files"] = len(matching_files)
                            saveQueuedBatchMetadata(
                                matching_files,
                                runtime_profile=self.batch_runtime_profile,
                                workflow_return=self.batch_workflow_return,
                            )
                            if not self._wait_batch_submit(est):
                                self._emit_batch_phase("canceled", est)
                                self.emit_log(
                                    "[BATCH] Canceled. Nothing was sent to the provider. "
                                    + ("The linked queue was preserved." if self.preserve_batch_queue else "The local queue was discarded.")
                                )
                                self.finished_signal.emit(True, "Batch canceled")
                                return
                            poll_result = self._run_batch_poll_fetch()
                            if poll_result is None:
                                self.finished_signal.emit(False, "Batch polling stopped")
                                return
                            if poll_result is False:
                                self.finished_signal.emit(
                                    False, "Batch provider failed; request queue preserved"
                                )
                                return
                    elif self.batch_resume_state == "queued":
                        # Resume a declined/interrupted collect: estimate + submit only.
                        self.emit_log(
                            "[BATCH] Resuming queued requests (skipping re-collect to avoid "
                            "duplicate live charges and a second batch submission)..."
                        )
                        n_requests = pendingBatchRequests()
                        if n_requests == 0:
                            batch_no_work = True
                            self._emit_batch_phase("no_work", {
                                "files": len(matching_files),
                            })
                            self.emit_log(
                                "[BATCH] Queue is empty. No provider batch was submitted."
                            )
                            run_consume = False
                        else:
                            self._emit_batch_phase("collect_done", {
                                "files": len(matching_files),
                                "requests": n_requests,
                            })
                            est = self._emit_batch_output(estimateBatchCost)
                            if est is not None:
                                est = dict(est)
                                est["files"] = len(matching_files)
                            if not self._wait_batch_submit(est):
                                self._emit_batch_phase("canceled", est)
                                self.emit_log(
                                    "[BATCH] Canceled. The local queue was discarded and "
                                    "nothing was sent to the provider."
                                )
                                self.finished_signal.emit(True, "Batch canceled")
                                return
                            poll_result = self._run_batch_poll_fetch()
                            if poll_result is None:
                                self.finished_signal.emit(False, "Batch polling stopped")
                                return
                            if poll_result is False:
                                self.finished_signal.emit(
                                    False, "Batch provider failed; request queue preserved"
                                )
                                return
                    elif self.batch_resume_state in {"submitted", "partially_submitted"}:
                        self._emit_batch_phase("polling")
                        self.emit_log(
                            "[BATCH] Resuming submitted batch..."
                            if self.batch_resume_state == "submitted"
                            else "[BATCH] Resuming partially submitted split batch..."
                        )
                        poll_result = self._run_batch_poll_fetch()
                        if poll_result is None:
                            self.finished_signal.emit(False, "Batch polling stopped")
                            return
                        if poll_result is False:
                            self.finished_signal.emit(
                                False, "Batch provider failed; request queue preserved"
                            )
                            return
                    else:
                        self.emit_log("[BATCH] Resuming from fetched results...")
                        try:
                            from util.vocab import BATCH_GLOSSARY_FREEZE_FILE

                            if not BATCH_GLOSSARY_FREEZE_FILE.is_file():
                                self.emit_log(
                                    "[BATCH] NOTE: no collect-time glossary freeze on disk. "
                                    "v5+ batch keys ignore glossary/SFX; freeze is only needed "
                                    "to rematch older (pre-v5) paid results."
                                )
                        except Exception:
                            pass

                    if run_consume and not self.should_stop:
                        try:
                            from util.batch_history import missing_result_count
                            present, expected = missing_result_count()
                            if expected and present < expected:
                                self.emit_log(
                                    f"[BATCH] WARNING: only {present}/{expected} results present. "
                                    "The consume pass will stop on a missing key; it will not "
                                    "make a full-price live request."
                                )
                        except Exception:
                            pass
                        self._emit_batch_phase("consume")
                        self.emit_log("[BATCH] Pass 2/2: writing translated files...")
                        self.emit_log(
                            "[BATCH] Pass 2 runs one file at a time so glossary "
                            "harvests from earlier files are available to later ones."
                        )
                        try:
                            from util.vocab import restore_batch_glossary_freeze_from_state

                            if restore_batch_glossary_freeze_from_state():
                                self.emit_log(
                                    "[BATCH] Restored collect-time glossary freeze."
                                )
                        except Exception:
                            pass
                        total_cost = self._run_files(matching_files, False, batch_phase="consume")
                elif use_batch_estimate:
                    from util.translation import (
                        clearEstimateRequests,
                        estimateCostComparison,
                        estimateTranslationCosts,
                    )

                    clearEstimateRequests(strict=True)
                    self.emit_log(
                        "[ESTIMATE] Building the same deduplicated request set "
                        "used by Batch Translate; nothing will be submitted."
                    )
                    estimate_started = time.monotonic()
                    try:
                        total_cost = self._run_files(
                            matching_files,
                            True,
                            batch_phase="estimate",
                        )
                        if total_cost not in {"Fail", "Stopped"} and not self.should_stop:
                            estimate = self._emit_batch_output(
                                estimateTranslationCosts
                            )
                            if estimate is None:
                                estimate = estimateCostComparison(0, 0)
                                estimate["requests"] = 0
                                estimate["basis"] = "request_queue"
                            estimate = dict(estimate)
                            estimate["files"] = len(matching_files)
                            estimate["elapsed_seconds"] = max(
                                0.0, time.monotonic() - estimate_started
                            )
                            self.estimate_summary = estimate
                            self.estimate_ready_signal.emit(estimate)
                            total_cost = _format_estimate_total(estimate)
                    finally:
                        clearEstimateRequests()
                else:
                    total_cost = self._run_files(matching_files, self.estimate_only)
            finally:
                os.chdir(old_cwd)

            # Clean up temporary files
            tmp_file = self.project_root / "csv.tmp"
            if tmp_file.exists():
                tmp_file.unlink()

            # Clean up any remaining temporary scripts
            temp_script = self.project_root / "temp_translation_script.py"
            if temp_script.exists():
                temp_script.unlink()

            # Ensure all processes are terminated
            if self.running_processes:
                for process in self.running_processes:
                    try:
                        if process.poll() is None:
                            process.terminate()
                            process.wait(timeout=1)
                    except:
                        pass
                self.running_processes.clear()

            # Report results
            if total_cost != "Fail" and not self.should_stop:
                if self.batch_mode:
                    try:
                        from util.translation import clearBatchFiles
                        clearBatchFiles(strict=True)
                    except Exception as exc:
                        self.emit_log(
                            "⚠ Batch output was written, but completed-batch recovery "
                            f"files could not be cleared: {exc}"
                        )
                    if not batch_no_work:
                        self._emit_batch_phase(
                            "done",
                            {
                                "mismatches": getattr(
                                    self, "_run_mismatch_count", 0
                                )
                            },
                        )
                self.emit_log("")
                self.emit_log(f"💰 {total_cost}")
                if self.batch_mode and batch_no_work:
                    self.emit_log("ℹ️ Batch scan completed with no work to submit.")
                elif self.batch_mode:
                    self.emit_log("✅ Batch translation completed!")
                elif not self.estimate_only:
                    self.emit_log("✅ Translation completed successfully!")
                else:
                    self.emit_log("✅ Estimation completed!")
                    try:
                        from util.translation import clear_estimate_written_sizes
                        clear_estimate_written_sizes()
                    except Exception:
                        pass
                if getattr(self, "_run_had_mismatch", False):
                    self.emit_log(
                        f"⚠ Completed with {_mismatch_summary(getattr(self, '_run_mismatch_count', 0))}; "
                        "original text was kept for those chunks. Review Issues in "
                        "the translation log."
                    )
                self.finished_signal.emit(True, str(total_cost))
            else:
                if not self.should_stop:
                    self.emit_log("❌ Translation failed!")
                    self.finished_signal.emit(False, "Translation failed")
                else:
                    # Only log the final stop message here
                    self.emit_log("🛑 Translation stopped by user")
                    self.finished_signal.emit(False, "Translation stopped")

        except Exception as e:
            error_msg = f"❌ Unexpected error: {str(e)}"
            self.emit_log(error_msg)
            self.finished_signal.emit(False, error_msg)

class TranslationTask(TranslationTaskCore):
    """Plain-Python adapter, with the same observable events as TranslationWorker."""

    def __init__(self, *args, **kwargs):
        for name in (
            "log", "progress", "item_progress", "file_error", "file_mismatch",
            "status", "finished", "batch_phase", "estimate_ready", "speaker_confirmation",
        ):
            setattr(self, name + "_signal", TaskSignal())
        self.initialize(*args, **kwargs)
