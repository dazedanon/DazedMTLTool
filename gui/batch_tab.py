#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch history tab - list / cancel / usage / redownload / resume."""

from __future__ import annotations

import os
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGridLayout,
    QPushButton,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QTextEdit,
    QMessageBox,
    QAbstractItemView,
    QSplitter,
    QSizePolicy,
)

from dotenv import load_dotenv
from gui.theme import COLORS
from gui.ui_components import (
    PageHeader,
    SectionCard,
    configure_action_button,
    make_page_layout,
)


class _BatchOpsWorker(QThread):
    """Run a blocking batch-history callable off the UI thread."""

    done = pyqtSignal(bool, str, object)  # ok, message, payload
    log = pyqtSignal(str)

    def __init__(self, task, project_root: Path):
        super().__init__()
        self._task = task
        self._project_root = project_root

    def run(self):
        old = os.getcwd()
        try:
            os.chdir(str(self._project_root))
            load_dotenv()
            ok, msg, payload = self._task(self.log.emit)
            self.done.emit(bool(ok), str(msg), payload)
        except Exception as exc:
            import traceback

            self.log.emit(traceback.format_exc())
            self.done.emit(False, f"Error: {exc}", None)
        finally:
            try:
                os.chdir(old)
            except Exception:
                pass


class BatchTab(QWidget):
    """Manage past and in-flight provider batches for this project."""

    COLUMNS = [
        "Batch ID",
        "Workflow",
        "Provider",
        "Status",
        "Created",
        "Requests",
        "Model",
        "Estimate",
        "Actual $",
        "Files",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.project_root = Path(
            getattr(parent, "project_root", None) or Path(__file__).resolve().parent.parent
        )
        self._worker: _BatchOpsWorker | None = None
        self._rows: list[dict] = []
        self._loaded_once = False
        self._init_ui()

    def showEvent(self, event):
        super().showEvent(event)
        # Refresh every time the Batches page is shown so live status stays current.
        if self._worker is not None and self._worker.isRunning():
            return
        self._loaded_once = True
        QTimer.singleShot(0, lambda: self.refresh_list(live=True))

    def _init_ui(self):
        layout = make_page_layout(self)
        layout.addWidget(PageHeader(
            "Batch History",
            "Review and manage local Claude, GPT, and Gemini batch runs. These actions never submit a new batch."
        ))

        actions_card = SectionCard(
            "Manage selected batches",
            "Refresh history, then select a batch to cancel it, inspect usage, download results, or resume it.",
        )
        layout.addWidget(actions_card)
        toolbar = QGridLayout()
        toolbar.setSpacing(8)

        self.refresh_btn = QPushButton("Refresh batches")
        self.refresh_btn.setToolTip("Reload local history and refresh live status for active batches")
        self.refresh_btn.clicked.connect(lambda: self.refresh_list(live=True))

        self.cancel_btn = QPushButton("Cancel selected")
        self.cancel_btn.setToolTip("Cancel selected in-progress batch(es)")
        self.cancel_btn.clicked.connect(self.cancel_selected)

        self.usage_btn = QPushButton("Calculate usage")
        self.usage_btn.setToolTip("Sum real billed tokens for the selected ended batch")
        self.usage_btn.clicked.connect(self.usage_selected)

        self.redownload_btn = QPushButton("Download results")
        self.redownload_btn.setToolTip("Re-fetch results into log/batch_results.json (no re-submit)")
        self.redownload_btn.clicked.connect(self.redownload_selected)

        self.resume_btn = QPushButton("Resume in Translation")
        self.resume_btn.setToolTip("Activate this batch and continue poll/consume on the Translation tab")
        self.resume_btn.clicked.connect(self.resume_selected)

        buttons = (
            self.refresh_btn,
            self.cancel_btn,
            self.usage_btn,
            self.redownload_btn,
            self.resume_btn,
        )
        for index, btn in enumerate(buttons):
            configure_action_button(btn, variant="secondary")
            btn.setMinimumWidth(176)
            btn.setMaximumWidth(360)
            toolbar.addWidget(btn, index // 3, index % 3)
        for column in range(3):
            toolbar.setColumnStretch(column, 1)
        actions_card.add_layout(toolbar)

        results_card = SectionCard(
            "Batch runs",
            "Review local batch status and operation details. No action here submits a new batch.",
        )
        results_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(results_card, 1)

        splitter = QSplitter(Qt.Vertical)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(
            f"QTableWidget{{background-color:{COLORS.canvas};color:{COLORS.text_secondary};"
            f"gridline-color:{COLORS.border};alternate-background-color:{COLORS.chrome};}}"
            f"QHeaderView::section{{background-color:{COLORS.surface_1};"
            f"color:{COLORS.text_secondary};padding:4px;border:1px solid {COLORS.border};}}"
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, len(self.COLUMNS)):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._update_button_states)
        splitter.addWidget(self.table)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Operation log…")
        self.log.setStyleSheet(
            f"QTextEdit{{background-color:{COLORS.canvas};color:{COLORS.text_secondary};"
            f"border:1px solid {COLORS.border};font-family:monospace;font-size:12px;}}"
        )
        splitter.addWidget(self.log)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        results_card.add_widget(splitter, 1)

        self._update_button_states()

    def _append_log(self, text: str):
        if not text:
            return
        self.log.append(text.rstrip())

    def _selected_entries(self) -> list[dict]:
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        out = []
        for r in rows:
            if 0 <= r < len(self._rows):
                out.append(self._rows[r])
        return out

    def _update_button_states(self):
        busy = self._worker is not None and self._worker.isRunning()
        entries = self._selected_entries()
        n = len(entries)
        self.refresh_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(
            not busy and n >= 1 and any(
                (e.get("api_status") == "in_progress") or (e.get("status") == "submitted")
                for e in entries
            )
        )
        self.usage_btn.setEnabled(not busy and n == 1)
        if n == 1 and entries[0].get("workflow") == "evaluation":
            self.usage_btn.setEnabled(False)
        self.redownload_btn.setEnabled(
            not busy
            and n == 1
            and entries[0].get("workflow") != "evaluation"
            and entries[0].get("status") in ("ended", "fetched", "consumed", "submitted", "canceling")
        )
        self.resume_btn.setEnabled(
            not busy
            and n == 1
            and entries[0].get("workflow") != "evaluation"
            and entries[0].get("status")
            in ("submitted", "canceling", "ended", "fetched")
        )

    def _set_busy(self, busy: bool):
        if busy:
            for btn in (
                self.refresh_btn,
                self.cancel_btn,
                self.usage_btn,
                self.redownload_btn,
                self.resume_btn,
            ):
                btn.setEnabled(False)
        else:
            self._update_button_states()

    def _clear_worker(self):
        if self.sender() is self._worker:
            self._worker = None

    def _run_task(self, task, on_done=None):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Busy", "A batch operation is already running.")
            return

        self._set_busy(True)
        worker = _BatchOpsWorker(task, self.project_root)
        self._worker = worker

        def _finished(ok, msg, payload):
            self._set_busy(False)
            if msg:
                self._append_log(msg)
            if on_done:
                try:
                    on_done(ok, msg, payload)
                except Exception as exc:
                    self._append_log(f"[BATCH] UI update failed: {exc}")

        worker.log.connect(self._append_log)
        worker.done.connect(_finished)
        # Release the reference only after run() returns. Clearing in the done
        # slot aborts with "QThread: Destroyed while thread is still running".
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._clear_worker)
        worker.start()

    def _populate_table(self, entries: list[dict]):
        self._rows = list(entries or [])
        self.table.setRowCount(len(self._rows))
        for r, entry in enumerate(self._rows):
            est = entry.get("cost_estimate") or {}
            est_s = ""
            if isinstance(est, dict) and est.get("batch_cached_cost") is not None:
                try:
                    est_s = f"${float(est['batch_cached_cost']):.2f}"
                except (TypeError, ValueError):
                    est_s = ""
            elif isinstance(est, dict) and est.get("cost_usd") is not None:
                try:
                    est_s = f"${float(est['cost_usd']):.2f}"
                except (TypeError, ValueError):
                    est_s = ""
            actual = entry.get("actual_cost")
            actual_s = f"${actual:.4f}" if isinstance(actual, (int, float)) else ""
            files = entry.get("file_set") or []
            if not isinstance(files, list):
                files = [str(files)]
            files_s = ", ".join(str(f) for f in files[:3])
            if len(files) > 3:
                files_s += f" (+{len(files) - 3})"
            values = [
                str(entry.get("id") or ""),
                "Evaluation" if entry.get("workflow") == "evaluation" else "Translation",
                str(entry.get("provider") or "anthropic").title(),
                str(entry.get("status") or ""),
                str(entry.get("created_at") or "")[:19],
                str(entry.get("request_count") or ""),
                str(entry.get("model") or ""),
                est_s,
                actual_s,
                files_s,
            ]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                if c == 0:
                    item.setData(Qt.UserRole, entry.get("id"))
                self.table.setItem(r, c, item)
        self._update_button_states()

    def refresh_list(self, live: bool = True):
        def task(log):
            from util.batch_history import list_local_batches

            log("[BATCH] Loading local history...")
            entries = list_local_batches(refresh_live=live)
            log(f"[BATCH] {len(entries)} batch(es) in history.")
            return True, f"Loaded {len(entries)} batch(es).", entries

        def done(ok, _msg, payload):
            if ok and isinstance(payload, list):
                self._populate_table(payload)

        self._run_task(task, on_done=done)

    def cancel_selected(self):
        entries = self._selected_entries()
        if not entries:
            return
        ids = [e["id"] for e in entries if e.get("id")]
        reply = QMessageBox.question(
            self,
            "Cancel Batch?",
            "Cancel the selected in-progress batch(es)?\n\n"
            "The provider may still finish and bill requests that were already "
            "in flight when cancel is received.\n"
            "This does not submit a new batch.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        def task(log):
            from util.batch_history import cancel_batches

            log(f"[BATCH] Canceling {len(ids)} batch(es)…")
            results = cancel_batches(ids)
            lines = []
            for r in results:
                if r.get("ok"):
                    lines.append(f"  canceled {r['id']} -> {r.get('api_status')}")
                else:
                    lines.append(f"  failed {r['id']}: {r.get('error')}")
            for line in lines:
                log(line)
            return True, "Cancel finished.", results

        def done(ok, _msg, _payload):
            self.refresh_list(live=False)

        self._run_task(task, on_done=done)

    def usage_selected(self):
        entries = self._selected_entries()
        if len(entries) != 1:
            return
        bid = entries[0]["id"]

        def task(log):
            from util.batch_history import usage_for_batch

            log(f"[BATCH] Computing usage for {bid}…")
            info = usage_for_batch(bid)
            u = info.get("usage") or {}
            log(
                f"[BATCH] tokens: in={u.get('input_tokens', 0)} out={u.get('output_tokens', 0)} "
                f"cache_read={u.get('cache_read_input_tokens', 0)} "
                f"cache_write={u.get('cache_creation_input_tokens', 0)} "
                f"thinking={u.get('thinking_tokens', 0)}"
            )
            cost = info.get("actual_cost")
            if cost is not None:
                log(f"[BATCH] estimated billed cost (batch 50% off): ${cost:.4f}")
            return True, "Usage updated.", info

        def done(ok, _msg, _payload):
            self.refresh_list(live=False)

        self._run_task(task, on_done=done)

    def redownload_selected(self):
        entries = self._selected_entries()
        if len(entries) != 1:
            return
        bid = entries[0]["id"]
        reply = QMessageBox.question(
            self,
            "Redownload Results?",
            f"Re-fetch results for {bid} into log/batch_results.json?\n\n"
            "This does not create a new batch or re-collect.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        def task(log):
            from util.batch_history import redownload_batch

            log(f"[BATCH] Redownloading {bid}…")
            info = redownload_batch(bid)
            log(
                f"[BATCH] redownload ok={info.get('succeeded')} err={info.get('errored')} "
                f"cost≈{info.get('actual_cost')}"
            )
            return True, "Redownload finished.", info

        def done(ok, msg, payload):
            self.refresh_list(live=False)
            if not ok:
                return
            reply = QMessageBox.question(
                self,
                "Resume Consume?",
                "Results are ready locally. Switch to Translation and resume consume now?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._resume_with_state("fetched", entries[0])

        self._run_task(task, on_done=done)

    def resume_selected(self):
        entries = self._selected_entries()
        if len(entries) != 1:
            return
        entry = entries[0]
        bid = entry["id"]

        def task(log):
            from util.batch_history import activate_for_resume

            log(f"[BATCH] Activating {bid} for resume…")
            state = activate_for_resume(bid)
            log(f"[BATCH] active resume state: {state}")
            return True, f"Activated ({state}).", {"state": state, "entry": entry}

        def done(ok, _msg, payload):
            self.refresh_list(live=False)
            if not ok or not payload:
                return
            self._resume_with_state(payload["state"], payload.get("entry") or entry)

        self._run_task(task, on_done=done)

    def _resume_with_state(self, resume_state: str, entry: dict):
        parent = self.parent_window
        if parent is None or not hasattr(parent, "translation_tab"):
            QMessageBox.warning(self, "Resume", "Translation tab is not available.")
            return
        tt = parent.translation_tab
        file_set = entry.get("file_set") or []
        if file_set and hasattr(tt, "select_files_by_name"):
            tt.select_files_by_name(file_set)
        # Switch to Translation page.
        if hasattr(parent, "switch_page"):
            page = getattr(parent, "PAGE_TRANSLATION", 4)
            parent.switch_page(page)
        reply = QMessageBox.question(
            self,
            "Start Resume?",
            f"Start Batch Translate resume ({resume_state}) on the Translation tab?\n\n"
            "This will not clear batch files or submit a new batch.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        tt.start_translation(forced_resume_state=resume_state)
