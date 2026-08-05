"""Ask before downloading the semi-manual workflow's extra parts, then do it.

The workflow needs numpy, OpenCV, an OCR client and — if the user wants
anything better than OpenCV's own two fills — a few hundred megabytes of neural
network weights. None of that is in ``requirements.txt``, so the first time
somebody presses *Edit text…* they are shown exactly what is missing, what it
costs and where it comes from, and nothing is fetched until they agree.

Afterwards the editor opens in the same process. See
``util/imagetools/resources.py`` for why no restart is needed, and for the
manifest itself — this file is only the face of it, and deliberately holds no
knowledge of what any particular resource is.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.theme import Spacing
from gui.ui_components import (
    SectionCard,
    configure_action_button,
    set_status_text,
)
from util.imagetools import resources as resmod


class ResourceWorker(QThread):
    """Runs the download off the UI thread.

    One signal per concern, the terminal state on ``finished_ok``, and every
    exception turned into a signal rather than allowed out of ``run`` - the
    convention the other workers in this application already follow.
    """

    progress = pyqtSignal(str, int, int)  # key, bytes done, bytes total (0 = unknown)
    message = pyqtSignal(str)
    finished_ok = pyqtSignal(bool, str)

    def __init__(self, chosen, parent=None):
        super().__init__(parent)
        self.chosen = list(chosen)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            resmod.install(
                self.chosen,
                progress=self.progress.emit,
                log=self.message.emit,
                should_stop=lambda: self._stop,
            )
        except resmod.Cancelled:
            self.finished_ok.emit(False, "Stopped. Nothing half-written was kept.")
            return
        except Exception as exc:
            self.finished_ok.emit(False, f"{type(exc).__name__}: {exc}")
            return
        self.finished_ok.emit(True, "Everything is ready.")


class _Row(QWidget):
    """One resource: tick box, size, and a bar that appears when it starts."""

    def __init__(self, resource, parent=None):
        super().__init__(parent)
        self.resource = resource

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(Spacing.SM)
        self.check = QCheckBox(resource.label)
        self.check.setChecked(resource.default)
        if resource.required:
            # Not a disabled tick box pretending to be a choice: the workflow
            # genuinely cannot start without these, so say so and move on.
            self.check.setChecked(True)
            self.check.setEnabled(False)
            self.check.setToolTip("The workflow cannot run without this.")
        top.addWidget(self.check, 1)
        self.size_label = QLabel(resmod.human(resmod.estimate([resource])))
        self.size_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self.size_label)
        layout.addLayout(top)

        detail = QLabel(resource.detail)
        detail.setWordWrap(True)
        detail.setIndent(20)
        detail.setEnabled(False)
        layout.addWidget(detail)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setMaximumHeight(4)
        self.bar.setVisible(False)
        layout.addWidget(self.bar)

    def wanted(self) -> bool:
        return self.check.isChecked()

    def start(self) -> None:
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)

    def advance(self, done: int, total: int) -> None:
        self.bar.setVisible(True)
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
        else:
            self.bar.setRange(0, 0)

    def done(self) -> None:
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.check.setText(f"{self.resource.label} — installed")


class ResourceDialog(QDialog):
    """What is missing, what it costs, and a Download button."""

    def __init__(self, missing, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Semi-manual image translation — extra parts")
        self.setMinimumWidth(620)
        self.worker = None
        self.installed_ok = False

        outer = QVBoxLayout(self)
        outer.setSpacing(Spacing.MD)

        card = SectionCard(
            "This workflow needs a few things that are not in the repository",
            "Reading text out of pictures needs OpenCV and an OCR client; "
            "rebuilding the artwork underneath the text can also use a neural "
            "network, which is where the size comes from. Everything is "
            "downloaded into this installation and nothing is sent anywhere.",
        )
        outer.addWidget(card)

        self.rows = []
        for resource in missing:
            row = _Row(resource)
            row.check.toggled.connect(self._retotal)
            card.add_widget(row)
            self.rows.append(row)

        self.total_label = QLabel("")
        card.add_widget(self.total_label)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setVisible(False)
        self.log.setMaximumHeight(180)
        outer.addWidget(self.log)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.skip_button = QPushButton("Skip extras")
        self.skip_button.setToolTip(
            "Open the editor with what is already installed. Any reconstruction "
            "method left out stays available to download later."
        )
        self.skip_button.clicked.connect(self._skip)
        # Only honest when the workflow can actually start.
        self.skip_button.setEnabled(resmod.ready())
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.download_button = QPushButton("Download")
        self.download_button.clicked.connect(self._download)
        for button, variant in (
            (self.skip_button, "secondary"),
            (self.cancel_button, "secondary"),
            (self.download_button, "primary"),
        ):
            configure_action_button(button, variant=variant)
            buttons.addWidget(button)
        outer.addLayout(buttons)

        self._retotal()

    # ------------------------------------------------------------- selection
    def chosen(self):
        return [row.resource for row in self.rows if row.wanted()]

    def _retotal(self) -> None:
        chosen = self.chosen()
        total = resmod.estimate(chosen)
        self.total_label.setText(
            f"About {resmod.human(total)} to download."
            if chosen else
            "Nothing selected."
        )
        self.download_button.setEnabled(bool(chosen))

    # -------------------------------------------------------------- download
    def _download(self) -> None:
        chosen = self.chosen()
        if not chosen:
            return
        self.log.setVisible(True)
        for row in self.rows:
            row.check.setEnabled(False)
        self.download_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        self.cancel_button.setText("Stop")
        set_status_text(self.status, "Downloading…", "info")

        self.worker = ResourceWorker(chosen, self)
        self.worker.progress.connect(self._progress)
        self.worker.message.connect(self._log)
        self.worker.finished_ok.connect(self._finished)
        self.worker.start()

    def _progress(self, key: str, done: int, total: int) -> None:
        for row in self.rows:
            if row.resource.key != key:
                continue
            if done or total:
                row.advance(done, total)
            else:
                row.start()

    def _log(self, line: str) -> None:
        self.log.appendPlainText(line)

    def _finished(self, ok: bool, message: str) -> None:
        self.worker = None
        self.cancel_button.setText("Close")
        self._log(message)
        if not ok:
            set_status_text(self.status, message, "error")
            # Whatever did land is kept, so a retry only fetches the rest.
            for row in self.rows:
                row.check.setEnabled(not resmod.installed(row.resource))
                if resmod.installed(row.resource):
                    row.done()
            self.download_button.setEnabled(True)
            self.download_button.setText("Try again")
            self.skip_button.setEnabled(resmod.ready())
            return
        for row in self.rows:
            row.done()
        set_status_text(self.status, message, "success")
        self.installed_ok = True
        self.accept()

    def _skip(self) -> None:
        self.installed_ok = True
        self.accept()

    # ------------------------------------------------------------- lifecycle
    def reject(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(5000)
            self.worker = None
        super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(5000)
            self.worker = None
        super().closeEvent(event)


def ensure_resources(parent=None) -> bool:
    """True when the semi-manual editor may be opened.

    Returns immediately when nothing is missing, so this costs one filesystem
    check on every launch after the first and the user never sees it twice.
    """
    outstanding = resmod.missing()
    if not outstanding:
        return True

    dialog = ResourceDialog(outstanding, parent)
    dialog.exec_()
    if not dialog.installed_ok:
        return False

    if not resmod.ready():
        QMessageBox.warning(
            parent,
            "Not ready yet",
            "The parts the workflow cannot run without are still missing, so "
            "there is nothing to open. The log in that window says what failed.",
        )
        return False
    return True
