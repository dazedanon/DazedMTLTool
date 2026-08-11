"""Background workers shared by the guided game workflows."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import jsbeautifier
from PyQt5.QtCore import QThread, pyqtSignal


class ScanWorker(QThread):
    done = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, data_path: str, engine: str):
        super().__init__()
        self.data_path = data_path
        self.engine = engine

    def run(self):
        try:
            from util.project_scanner import list_data_files

            self.done.emit(list_data_files(self.data_path, self.engine))
        except Exception as exc:
            self.error.emit(str(exc))


class ImportWorker(QThread):
    done = pyqtSignal(int, list)
    log = pyqtSignal(str)

    def __init__(self, file_items: list[dict], dest_dir: str):
        super().__init__()
        self.file_items = file_items
        self.dest_dir = dest_dir

    def run(self):
        try:
            from util.project_scanner import import_to_files

            dest = Path(self.dest_dir)
            if dest.exists():
                removed = 0
                for path in dest.iterdir():
                    if path.name == ".gitkeep":
                        continue
                    try:
                        if path.is_file():
                            path.unlink()
                        elif path.is_dir():
                            shutil.rmtree(path)
                        else:
                            continue
                        removed += 1
                    except Exception as exc:
                        self.log.emit(f"  ⚠ Could not remove {path.name}: {exc}")
                if removed:
                    self.log.emit(f"Cleared {removed} existing file(s) from {dest.name}/")

            self.log.emit(f"Importing {len(self.file_items)} file(s) into files/ …")
            count, errors = import_to_files(self.file_items, self.dest_dir)
            self.done.emit(count, errors)
        except Exception as exc:
            self.done.emit(0, [str(exc)])


class ExportWorker(QThread):
    done = pyqtSignal(int, list)
    log = pyqtSignal(str)

    def __init__(self, game_data_path: str, filter_names: list[str] | None = None):
        super().__init__()
        self.game_data_path = game_data_path
        self.filter_names = filter_names

    def run(self):
        try:
            from util.project_scanner import export_to_game

            if self.filter_names:
                self.log.emit(
                    f"Exporting {len(self.filter_names)} active file(s) → "
                    f"{self.game_data_path} …"
                )
            else:
                self.log.emit(f"Exporting translated/ → {self.game_data_path} …")
            count, errors = export_to_game(
                "translated", self.game_data_path, filenames=self.filter_names
            )
            self.done.emit(count, errors)
        except Exception as exc:
            self.done.emit(0, [str(exc)])


class RpgMakerRewrapWorker(QThread):
    done = pyqtSignal(object, bool)
    failed = pyqtSignal(str)

    def __init__(self, directory: str, options, file_names: list[str], *, apply: bool):
        super().__init__()
        self.directory = directory
        self.options = options
        self.file_names = list(file_names)
        self.apply = bool(apply)

    def run(self):
        try:
            from util.rpgmaker_rewrap import rewrap_directory

            report = rewrap_directory(
                self.directory,
                self.options,
                file_names=self.file_names,
                apply=self.apply,
            )
            self.done.emit(report, self.apply)
        except Exception as exc:
            self.failed.emit(str(exc))


class RpgMakerQAPrepareWorker(QThread):
    """Build or reuse one local AI-helper QA task off the UI thread."""

    done = pyqtSignal(str, object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        game_root: str,
        data_root: str,
        focus: str,
        output_root: str,
    ):
        super().__init__()
        self.game_root = game_root
        self.data_root = data_root
        self.focus = focus
        self.output_root = output_root

    def run(self):
        try:
            from util.rpgmaker_qa import prepare_task

            task_dir, task_status = prepare_task(
                self.game_root,
                self.data_root,
                self.focus,
                self.output_root,
            )
            self.done.emit(str(task_dir), task_status)
        except Exception as exc:
            self.failed.emit(str(exc))


class SubprocessWorker(QThread):
    done = pyqtSignal(bool, str)
    log = pyqtSignal(str)

    def __init__(self, cmd: list, cwd: str, label: str = ""):
        super().__init__()
        self.cmd = cmd
        self.cwd = cwd
        self.label = label or cmd[0]

    def run(self):
        try:
            executable = shutil.which(self.cmd[0])
            if executable is None:
                self.done.emit(
                    False,
                    f"'{self.cmd[0]}' not found on PATH. "
                    "Make sure it is installed and accessible from the terminal.",
                )
                return
            self.log.emit(f"$ {' '.join(str(item) for item in self.cmd)}  —  cwd: {self.cwd}")
            process = subprocess.Popen(
                self.cmd,
                cwd=self.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if process.stdout is not None:
                for line in process.stdout:
                    stripped = line.rstrip("\n")
                    if stripped:
                        self.log.emit(stripped)
            process.wait()
            if process.returncode == 0:
                self.done.emit(True, f"{self.label}: finished successfully.")
            else:
                self.done.emit(False, f"{self.label}: exited with code {process.returncode}.")
        except Exception as exc:
            self.done.emit(False, f"{self.label}: {exc}")


class JsonFormatWorker(QThread):
    done = pyqtSignal(bool, str)
    log = pyqtSignal(str)

    def __init__(self, data_path: str):
        super().__init__()
        self.data_path = data_path

    def run(self):
        try:
            from util.dazedformat import format_json_files

            self.log.emit(f"Formatting JSON files in {self.data_path} …")
            count, errors = format_json_files(self.data_path, log=self.log.emit)
            for error in errors:
                self.log.emit(f"  ⚠  {error}")
            if errors:
                self.done.emit(False, f"dazedformat: {count} formatted, {len(errors)} error(s).")
            else:
                self.done.emit(True, f"dazedformat: {count} file(s) formatted successfully.")
        except Exception as exc:
            self.done.emit(False, f"dazedformat error: {exc}")


class FileCopyWorker(QThread):
    done = pyqtSignal(int, list)
    log = pyqtSignal(str)

    def __init__(self, src: str, dst: str, skip_names: frozenset[str] | None = None):
        super().__init__()
        self.src = src
        self.dst = dst
        self.skip_names = skip_names or frozenset()

    def run(self):
        src = Path(self.src)
        dst = Path(self.dst)
        if not src.is_dir():
            self.done.emit(0, [f"Source folder not found: {src}"])
            return
        dst.mkdir(parents=True, exist_ok=True)
        copied = 0
        errors: list[str] = []
        self.log.emit(f"Copying {src} → {dst} …")
        for path in src.rglob("*"):
            if not path.is_file():
                continue
            if path.name in self.skip_names:
                self.log.emit(f"  skipped {path.relative_to(src)}")
                continue
            relative = path.relative_to(src)
            target = dst / relative
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                copied += 1
                self.log.emit(f"  copied {relative}")
            except Exception as exc:
                errors.append(f"{relative}: {exc}")
        self.done.emit(copied, errors)


class ReleaseZipWorker(QThread):
    done = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)

    def __init__(self, game_root: str, output_path: str):
        super().__init__()
        self.game_root = game_root
        self.output_path = output_path

    def run(self):
        try:
            from util.release_package import create_release_zip

            result = create_release_zip(
                self.game_root,
                self.output_path,
                progress=lambda current, total, label: self.progress.emit(
                    current, total, label
                ),
            )
            self.done.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class JsFormatWorker(QThread):
    done = pyqtSignal(bool, str)
    log = pyqtSignal(str)

    def __init__(self, js_path: str):
        super().__init__()
        self.js_path = js_path

    def run(self):
        try:
            path = Path(self.js_path)
            self.log.emit(f"Formatting {path.name} …")
            original = path.read_text(encoding="utf-8")
            options = jsbeautifier.default_options()
            options.indent_size = 2
            options.indent_char = " "
            options.max_preserve_newlines = 2
            options.preserve_newlines = True
            options.end_with_newline = True
            formatted = jsbeautifier.beautify(original, options)
            path.write_text(formatted, encoding="utf-8")
            self.done.emit(
                True,
                f"plugins.js formatted successfully ({len(formatted):,} chars).",
            )
        except Exception as exc:
            self.done.emit(False, f"Format error: {exc}")
