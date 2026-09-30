"""Edit the shared reference registry using engine-neutral, extracted JSON pairs."""

from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QVBoxLayout

from gui.ui_components import PageHeader, make_action_button, set_status_text
from util.reference_games import add_embedded_reference, add_paired_reference, load_registry, remove_reference


class ReferenceGamesDialog(QDialog):
    references_changed = pyqtSignal()

    def __init__(self, parent=None, *, game_root_fn):
        super().__init__(parent)
        self._game_root_fn = game_root_fn
        self.setWindowTitle("Reference translations")
        self.resize(780, 460)
        layout = QVBoxLayout(self)
        layout.addWidget(PageHeader("Reference translations", "These are the same project references used by Workflow and QA."))
        hint = QLabel(
            "Add Japanese and English JSON folders with matching structure. For another engine, "
            "use its extracted text first. DazedTL translations with _original fields can be added "
            "as one folder. Matches are advisory; this game’s source and glossary remain authoritative."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.references = QListWidget()
        layout.addWidget(self.references, 1)
        actions = QHBoxLayout()
        for title, callback in (
            ("Add JP / EN pair", self._add_pair),
            ("Add DazedTL translation", self._add_embedded),
            ("Remove selected", self._remove),
            ("Reload", self.reload),
        ):
            button = make_action_button(title)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def _root(self):
        raw = self._game_root_fn()
        if not raw:
            raise ValueError("Choose and load a game first.")
        return Path(raw)

    def reload(self):
        self.references.clear()
        try:
            root = self._root()
            registry = load_registry(root)
            for entry in registry["references"]:
                item = QListWidgetItem(f"{entry['title']} ({entry['mode']})")
                item.setData(Qt.UserRole, entry["id"])
                item.setToolTip(entry["translated_data"])
                self.references.addItem(item)
            set_status_text(self.status, f"{len(registry['references'])} reference(s) for {root.name}.", "info")
        except (OSError, ValueError) as exc:
            set_status_text(self.status, str(exc), "error")

    def _add_pair(self):
        try:
            root = self._root()
            source = QFileDialog.getExistingDirectory(self, "Japanese reference JSON folder")
            if not source:
                return
            translated = QFileDialog.getExistingDirectory(self, "English reference JSON folder")
            if not translated:
                return
            title, ok = QInputDialog.getText(self, "Reference name", "Name", text=Path(translated).parent.name)
            if not ok:
                return
            add_paired_reference(root, title, source, translated)
            self.reload()
            self.references_changed.emit()
        except (OSError, ValueError) as exc:
            set_status_text(self.status, str(exc), "error")

    def _add_embedded(self):
        try:
            root = self._root()
            folder = QFileDialog.getExistingDirectory(self, "DazedTL translated JSON folder")
            if not folder:
                return
            title, ok = QInputDialog.getText(self, "Reference name", "Name", text=Path(folder).parent.name)
            if not ok:
                return
            add_embedded_reference(root, title, folder)
            self.reload()
            self.references_changed.emit()
        except (OSError, ValueError) as exc:
            set_status_text(self.status, str(exc), "error")

    def _remove(self):
        item = self.references.currentItem()
        if item is None:
            return
        try:
            remove_reference(self._root(), item.data(Qt.UserRole))
            self.reload()
            self.references_changed.emit()
        except (OSError, ValueError) as exc:
            set_status_text(self.status, str(exc), "error")
