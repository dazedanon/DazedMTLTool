"""Engine-aware visual image workspace and patch manager."""

from __future__ import annotations

from pathlib import Path
import hashlib

from PyQt5.QtCore import (
    QPoint,
    Qt,
    QSize,
    QThread,
    pyqtSignal,
    QSettings,
    QUrl,
)
from PyQt5.QtGui import QColor, QDesktopServices, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QListView,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from util.paths import APP_NAME, ORG_NAME
from util.skills import load_clipboard_skill

from util.image_manager import (
    ImageAsset,
    PROFILE_AUTO,
    PROFILE_GENERIC,
    PROFILE_RPGMAKER_MVMZ,
    detect_image_engine,
    editable_workspace_root,
    ensure_editable_workspace,
    get_image_profile,
    make_profile_assets_editable,
    normalize_generic_image_root,
    prepare_profile_assets_for_patch,
    preview_profile_png_bytes,
    profile_label,
    registered_image_profiles,
    scan_profile_assets,
    thumbnail_profile_png_bytes,
)
from util.rpgmaker_images import (
    migrate_legacy_editable_workspace,
    read_encryption_key,
    remove_editable_assets,
    resolve_content_root,
)


_ASSET_ID_ROLE = Qt.UserRole + 1
_PAGE_SIZE = 1000


class _BoundedComboBox(QComboBox):
    """Keep large combo popups on-screen and scrollable."""

    _MAX_VISIBLE_ROWS = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        view = QListView(self)
        view.setVerticalScrollMode(QAbstractItemView.ScrollPerItem)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        view.setTextElideMode(Qt.ElideMiddle)
        view.setUniformItemSizes(True)
        view.setStyleSheet(
            "QListView {"
            "  background: #404040; color: #f2f2f2;"
            "  border: 1px solid #5a5a5a; outline: none; padding: 3px;"
            "}"
            "QListView::item { min-height: 30px; padding: 3px 8px; }"
            "QListView::item:selected { background: #087dcc; color: white; }"
            "QScrollBar:vertical { background: #303030; width: 12px; margin: 0; }"
            "QScrollBar::handle:vertical {"
            "  background: #777; min-height: 28px; border-radius: 5px;"
            "}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {"
            "  height: 0;"
            "}"
        )
        self.setView(view)
        self.setMaxVisibleItems(self._MAX_VISIBLE_ROWS)

    def showPopup(self) -> None:
        self.view().setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOn
            if self.count() > self._MAX_VISIBLE_ROWS
            else Qt.ScrollBarAsNeeded
        )
        super().showPopup()
        view = self.view()
        popup = view.window()
        screen = QApplication.screenAt(self.mapToGlobal(self.rect().center()))
        screen = screen or QApplication.primaryScreen()
        if screen is None:
            return

        available = screen.availableGeometry()
        row_height = view.sizeHintForRow(0)
        if row_height <= 0:
            row_height = self.fontMetrics().height() + 10
        visible_rows = min(max(1, self.count()), self._MAX_VISIBLE_ROWS)
        height_cap = min(
            row_height * visible_rows + view.frameWidth() * 2 + 8,
            max(row_height * 4, int(available.height() * 0.6)),
        )
        popup_height = min(popup.height(), height_cap)
        popup_width = min(max(popup.width(), self.width()), available.width())

        combo_top_left = self.mapToGlobal(QPoint(0, 0))
        below_y = combo_top_left.y() + self.height()
        above_y = combo_top_left.y() - popup_height
        if below_y + popup_height <= available.bottom() + 1:
            popup_y = below_y
        elif above_y >= available.top():
            popup_y = above_y
        else:
            popup_y = max(
                available.top(),
                min(popup.y(), available.bottom() - popup_height + 1),
            )
        popup_x = max(
            available.left(),
            min(combo_top_left.x(), available.right() - popup_width + 1),
        )
        popup.setGeometry(popup_x, popup_y, popup_width, popup_height)
        if self.currentIndex() >= 0:
            view.scrollTo(
                self.model().index(self.currentIndex(), self.modelColumn()),
                QAbstractItemView.PositionAtCenter,
            )


class _UserSelectionList(QListWidget):
    """Report user selection changes without reacting to list rebuilding."""

    userSelectionChanged = pyqtSignal()
    deleteRequested = pyqtSignal()

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        self.userSelectionChanged.emit()

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self.userSelectionChanged.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Delete:
            self.deleteRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)
        self.userSelectionChanged.emit()


class _ImageScanWorker(QThread):
    done = pyqtSignal(int, object)
    error = pyqtSignal(int, str)

    def __init__(
        self,
        generation: int,
        game_root: Path,
        engine_id: str,
        image_root: Path | None,
    ):
        super().__init__()
        self.generation = generation
        self.game_root = game_root
        self.engine_id = engine_id
        self.image_root = image_root

    def run(self) -> None:
        try:
            self.done.emit(
                self.generation,
                scan_profile_assets(self.engine_id, self.game_root, self.image_root),
            )
        except Exception as exc:
            self.error.emit(self.generation, str(exc))


class _ThumbnailWorker(QThread):
    done = pyqtSignal(int, object)

    def __init__(
        self,
        generation: int,
        assets: list[ImageAsset],
        key: bytes | None,
        engine_id: str = PROFILE_RPGMAKER_MVMZ,
    ):
        super().__init__()
        self.generation = generation
        self.assets = assets
        self.key = key
        self.engine_id = engine_id

    def run(self) -> None:
        thumbnails: dict[str, bytes] = {}
        for asset in self.assets:
            if self.isInterruptionRequested():
                return
            try:
                data = thumbnail_profile_png_bytes(
                    self.engine_id, asset, self.key, size=112
                )
            except Exception:
                data = b""
            thumbnails[asset.asset_id] = data
        self.done.emit(self.generation, thumbnails)


class _ImageActionWorker(QThread):
    status = pyqtSignal(str)
    done = pyqtSignal(str, object)
    error = pyqtSignal(str)

    def __init__(
        self,
        action: str,
        game_root: Path,
        assets: list[ImageAsset],
        key: bytes | None,
        engine_id: str = PROFILE_RPGMAKER_MVMZ,
    ):
        super().__init__()
        self.action = action
        self.game_root = game_root
        self.assets = assets
        self.key = key
        self.engine_id = engine_id

    def run(self) -> None:
        try:
            if self.action in {"decrypt", "make_editable"}:
                result = make_profile_assets_editable(
                    self.engine_id,
                    self.game_root,
                    self.assets,
                    self.key,
                    progress=self.status.emit,
                )
            elif self.action == "remove":
                result = remove_editable_assets(
                    self.game_root, self.assets, progress=self.status.emit
                )
            else:
                result = prepare_profile_assets_for_patch(
                    self.engine_id,
                    self.game_root,
                    self.assets,
                    self.key,
                    progress=self.status.emit,
                )
            self.done.emit(self.action, result)
        except Exception as exc:
            self.error.emit(str(exc))


class ImageManager(QWidget):
    """Paginated contact sheet for projects containing thousands of images."""

    def __init__(
        self,
        game_root: str | Path | None = None,
        parent=None,
        settings: QSettings | None = None,
    ):
        super().__init__(parent)
        self.settings = settings or QSettings(ORG_NAME, APP_NAME)
        saved_root = str(self.settings.value("workflow/last_game_folder", "") or "")
        initial_root = str(game_root or saved_root).strip()
        self.game_root = Path(initial_root).expanduser().resolve() if initial_root else None
        self.assets: list[ImageAsset] = []
        self.assets_by_id: dict[str, ImageAsset] = {}
        self.filtered_assets: list[ImageAsset] = []
        self.selected_ids: set[str] = set()
        self.page = 0
        self.key: bytes | None = None
        self.engine_id = PROFILE_RPGMAKER_MVMZ
        self.engine_detection = None
        self.generic_image_root: Path | None = None
        self._loading_engine_ui = False
        self._scan_worker: _ImageScanWorker | None = None
        self._scan_workers: list[_ImageScanWorker] = []
        self._scan_generation = 0
        self._thumbnail_worker: _ThumbnailWorker | None = None
        self._thumbnail_workers: list[_ThumbnailWorker] = []
        self._action_worker: _ImageActionWorker | None = None
        self._thumbnail_generation = 0

        self._build_ui()
        if self.game_root:
            self.folder_edit.setText(str(self.game_root))
            self._load_project()
        else:
            self.status_label.setText("Select a game folder to begin.")
            self._set_actions_enabled(False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 12)
        title = QLabel("Image Manager")
        title.setStyleSheet("font-size:18px;font-weight:bold;color:#e0e0e0;")
        root.addWidget(title)
        intro = QLabel(
            "Choose an engine profile, make images editable under .dazedtl/images, edit the "
            "PNG copies, then patch highlighted images or every editable image. "
            "Pages keep very large games responsive."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#b8b8b8;font-size:13px;padding:2px 0 6px 0;")
        root.addWidget(intro)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Game folder:"))
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Select a game folder…")
        self.folder_edit.returnPressed.connect(self._load_project)
        folder_row.addWidget(self.folder_edit, 1)
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._browse_game_root)
        folder_row.addWidget(browse_button)
        load_button = QPushButton("Load")
        load_button.clicked.connect(self._load_project)
        folder_row.addWidget(load_button)
        root.addLayout(folder_row)

        engine_row = QHBoxLayout()
        engine_row.addWidget(QLabel("Engine:"))
        self.engine_combo = QComboBox()
        self.engine_combo.addItem("Auto-detect", PROFILE_AUTO)
        for profile in registered_image_profiles():
            self.engine_combo.addItem(profile.label, profile.engine_id)
        self.engine_combo.currentIndexChanged.connect(self._engine_changed)
        engine_row.addWidget(self.engine_combo)
        self.engine_detection_label = QLabel("Select a game folder to detect its image layout.")
        self.engine_detection_label.setWordWrap(True)
        self.engine_detection_label.setStyleSheet("color:#9d9d9d;font-size:12px;")
        engine_row.addWidget(self.engine_detection_label, 1)
        self.migrate_legacy_button = QPushButton("Migrate old workspace")
        self.migrate_legacy_button.setToolTip(
            "Move images from the former DazedTL_Images folder into .dazedtl/images."
        )
        self.migrate_legacy_button.clicked.connect(self._migrate_legacy_workspace)
        self.migrate_legacy_button.hide()
        engine_row.addWidget(self.migrate_legacy_button)
        root.addLayout(engine_row)

        self.generic_root_host = QWidget()
        generic_root_row = QHBoxLayout(self.generic_root_host)
        generic_root_row.setContentsMargins(0, 0, 0, 0)
        generic_root_row.addWidget(QLabel("Image folder:"))
        self.generic_root_edit = QLineEdit()
        self.generic_root_edit.setPlaceholderText(
            "Choose the folder containing loose PNG images…"
        )
        self.generic_root_edit.returnPressed.connect(self._generic_root_changed)
        generic_root_row.addWidget(self.generic_root_edit, 1)
        self.generic_root_button = QPushButton("Browse…")
        self.generic_root_button.clicked.connect(self._browse_generic_root)
        generic_root_row.addWidget(self.generic_root_button)
        root.addWidget(self.generic_root_host)
        self.generic_root_host.hide()

        filters = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter by any part of the folder or filename…")
        self.search_edit.textChanged.connect(self._apply_filters)
        filters.addWidget(self.search_edit, 2)
        self.folder_combo = _BoundedComboBox()
        self.folder_combo.addItem("All folders", "")
        self.folder_combo.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self.folder_combo, 1)
        self.state_combo = QComboBox()
        self.state_combo.addItem("All images", "all")
        self.state_combo.addItem("Editable images", "editable")
        self.state_combo.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self.state_combo)
        root.addLayout(filters)

        splitter = QSplitter(Qt.Horizontal)
        self.image_list = _UserSelectionList()
        self.image_list.setViewMode(QListWidget.IconMode)
        self.image_list.setResizeMode(QListWidget.Adjust)
        self.image_list.setMovement(QListWidget.Static)
        self.image_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.image_list.setIconSize(QSize(112, 112))
        self.image_list.setGridSize(QSize(160, 160))
        self.image_list.setUniformItemSizes(True)
        self.image_list.setWordWrap(True)
        self.image_list.setSpacing(4)
        self.image_list.setObjectName("rpgImageList")
        self.image_list.setStyleSheet(
            "QListWidget#rpgImageList{background:#1e1e1e;color:#fff;"
            "border:1px solid #555;padding:3px;outline:none;}"
            "QListWidget#rpgImageList::item{border:1px solid transparent;"
            "padding:3px;background:transparent;}"
            "QListWidget#rpgImageList::item:selected{background:#264f78;"
            "border-color:#4b8dc0;color:#fff;}"
            "QListWidget#rpgImageList::item:hover:!selected{background:#333;"
            "border-color:#555;}"
        )
        self.image_list.userSelectionChanged.connect(self._selection_changed)
        self.image_list.deleteRequested.connect(self._remove_highlighted)
        self.image_list.currentItemChanged.connect(self._show_preview)
        self.image_list.setToolTip(
            "Click highlights one image. Ctrl-click toggles individual images, Shift-click "
            "selects a range, and Ctrl+A highlights the current page."
        )
        splitter.addWidget(self.image_list)

        preview_host = QWidget()
        preview_layout = QVBoxLayout(preview_host)
        self.preview_label = QLabel("Select an image to preview it")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(300, 300)
        self.preview_label.setStyleSheet(
            "background:#171717;border:1px solid #3c3c3c;color:#777;"
        )
        preview_layout.addWidget(self.preview_label, 1)
        self.path_label = QLabel()
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.path_label.setStyleSheet("color:#c8c8c8;font-size:12px;padding:5px;")
        preview_layout.addWidget(self.path_label)
        splitter.addWidget(preview_host)
        splitter.setSizes([850, 350])
        root.addWidget(splitter, 1)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(12)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.open_workspace_button = QPushButton("Open")
        self.open_workspace_button.setToolTip(
            "Open the highlighted image's editable folder, the chosen folder filter, or the "
            "editable img root."
        )
        self.open_workspace_button.clicked.connect(self._open_editable_folder)
        self.copy_translation_button = QPushButton("Copy skill")
        self.copy_translation_button.setToolTip(
            "Copy an agent-ready bitmap translation skill scoped to every PNG in the editable "
            "image folder. Paste it into Codex, Cursor, Copilot, or a similar coding agent."
        )
        self.copy_translation_button.clicked.connect(self._copy_translation_skill)
        self.decrypt_selected_button = QPushButton("Decrypt")
        self.decrypt_selected_button.clicked.connect(self._decrypt_checked)
        self.decrypt_all_button = QPushButton("Decrypt all")
        self.decrypt_all_button.clicked.connect(self._decrypt_all)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setToolTip(
            "Delete highlighted PNG copies from the editable folder. Runtime images remain "
            "untouched and can be decrypted again. The Delete key does the same thing."
        )
        self.remove_button.clicked.connect(self._remove_highlighted)
        self.prepare_button = QPushButton("Patch all")
        self.prepare_button.setStyleSheet(
            "QPushButton{border:1px solid #4ec9b0;color:#4ec9b0;font-weight:bold;padding:6px 14px;}"
            "QPushButton:hover{background:#18352f;}"
        )
        self.prepare_button.setToolTip(
            "With highlighted images, patch only their editable PNGs. With no highlights, patch "
            "every editable PNG. Editable copies remain in .dazedtl/images until removed."
        )
        self.prepare_button.clicked.connect(self._prepare_checked)
        action_buttons = (
            self.open_workspace_button,
            self.copy_translation_button,
            self.decrypt_selected_button,
            self.decrypt_all_button,
            self.remove_button,
            self.prepare_button,
        )
        for button in action_buttons:
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            action_row.addWidget(button, 1)
        controls_row.addLayout(action_row, 1)

        page_row = QHBoxLayout()
        page_row.setSpacing(8)
        self.previous_button = QPushButton("← Previous")
        self.previous_button.clicked.connect(lambda: self._change_page(-1))
        page_row.addWidget(self.previous_button)
        self.page_label = QLabel("Page 0 / 0")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setMinimumWidth(210)
        page_row.addWidget(self.page_label)
        self.next_button = QPushButton("Next →")
        self.next_button.clicked.connect(lambda: self._change_page(1))
        page_row.addWidget(self.next_button)
        nav_width = max(self.previous_button.sizeHint().width(), self.next_button.sizeHint().width())
        self.previous_button.setFixedWidth(nav_width)
        self.next_button.setFixedWidth(nav_width)
        common_height = max(
            40,
            *(button.sizeHint().height() for button in (*action_buttons, self.previous_button, self.next_button)),
        )
        for button in (*action_buttons, self.previous_button, self.next_button):
            button.setFixedHeight(common_height)
        controls_row.addLayout(page_row)
        root.addLayout(controls_row)

        self.status_label = QLabel("Scanning image folders…")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color:#8fbc8f;padding:4px 0;")
        root.addWidget(self.status_label)

    def _browse_game_root(self) -> None:
        start = self.folder_edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select Game Folder", start)
        if folder:
            self.folder_edit.setText(folder)
            self._load_project()

    def _project_settings_prefix(self) -> str:
        if self.game_root is None:
            return "images/projects/none"
        digest = hashlib.sha256(str(self.game_root).encode("utf-8")).hexdigest()[:16]
        return f"images/projects/{digest}"

    def _load_project_preferences(self) -> None:
        prefix = self._project_settings_prefix()
        selected = str(self.settings.value(f"{prefix}/engine", PROFILE_AUTO) or PROFILE_AUTO)
        if self.engine_combo.findData(selected) < 0:
            selected = PROFILE_AUTO
        saved_image_root = str(
            self.settings.value(f"{prefix}/generic_image_root", "") or ""
        ).strip()
        self._loading_engine_ui = True
        try:
            self.engine_combo.setCurrentIndex(self.engine_combo.findData(selected))
            self.generic_root_edit.setText(saved_image_root)
        finally:
            self._loading_engine_ui = False

    def _save_project_preferences(self) -> None:
        if self.game_root is None:
            return
        prefix = self._project_settings_prefix()
        self.settings.setValue(f"{prefix}/engine", self.engine_combo.currentData())
        self.settings.setValue(
            f"{prefix}/generic_image_root", self.generic_root_edit.text().strip()
        )

    def _engine_changed(self) -> None:
        if self._loading_engine_ui or self.game_root is None:
            return
        self._save_project_preferences()
        self.selected_ids.clear()
        self._configure_engine_and_scan()

    def _browse_generic_root(self) -> None:
        if self.game_root is None:
            QMessageBox.information(self, "Image Folder", "Select a game folder first.")
            return
        start = self.generic_root_edit.text().strip() or str(self.game_root)
        folder = QFileDialog.getExistingDirectory(
            self, "Select Loose Image Folder", start
        )
        if folder:
            self.generic_root_edit.setText(folder)
            self._generic_root_changed()

    def _migrate_legacy_workspace(self) -> None:
        if self.game_root is None:
            return
        legacy = self.game_root / "DazedTL_Images"
        if not legacy.is_dir():
            self.migrate_legacy_button.hide()
            return
        answer = QMessageBox.question(
            self,
            "Migrate Old Editable Images",
            "Move editable images from DazedTL_Images into .dazedtl/images?\n\n"
            "Conflicting files are preserved under .dazedtl/legacy_image_conflicts. "
            "Runtime game images are not changed.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            moved = migrate_legacy_editable_workspace(self.game_root)
        except Exception as exc:
            QMessageBox.warning(self, "Editable Image Migration", str(exc))
            return
        self.migrate_legacy_button.hide()
        self.status_label.setText(f"Migrated {moved:,} legacy editable image(s).")
        self._start_scan()

    def _generic_root_changed(self) -> None:
        if self.game_root is None:
            return
        try:
            chosen = normalize_generic_image_root(
                self.game_root, self.generic_root_edit.text().strip()
            )
        except Exception as exc:
            QMessageBox.warning(self, "Image Folder", str(exc))
            return
        self.generic_root_edit.setText(str(chosen))
        self.generic_image_root = chosen
        self._save_project_preferences()
        self.selected_ids.clear()
        self._start_scan()

    def _configure_engine_and_scan(self) -> None:
        if self.game_root is None:
            return
        # Invalidate any scan started for the previous profile before returning
        # early for an incomplete Generic configuration.
        self._scan_generation += 1
        selected = self.engine_combo.currentData() or PROFILE_AUTO
        try:
            self.engine_detection = detect_image_engine(self.game_root)
        except Exception as exc:
            self.engine_detection = None
            self.status_label.setText(f"Engine detection failed: {exc}")
            self._set_actions_enabled(False)
            return
        self.engine_id = (
            self.engine_detection.engine_id if selected == PROFILE_AUTO else selected
        )
        if selected == PROFILE_AUTO:
            detected = profile_label(self.engine_id)
            self.engine_detection_label.setText(
                f"Auto: {detected} ({self.engine_detection.confidence}) — "
                f"{self.engine_detection.reason}"
            )
        else:
            self.engine_detection_label.setText(
                f"Manual: {profile_label(self.engine_id)} — "
                f"auto-detection reported {profile_label(self.engine_detection.engine_id)}"
            )

        is_generic = self.engine_id == PROFILE_GENERIC
        self.generic_root_host.setVisible(is_generic)
        self.migrate_legacy_button.setVisible(
            self.engine_id == PROFILE_RPGMAKER_MVMZ
            and (self.game_root / "DazedTL_Images").is_dir()
        )
        self.generic_image_root = None
        if is_generic:
            raw_root = self.generic_root_edit.text().strip()
            if not raw_root and self.engine_detection.suggested_image_root is not None:
                raw_root = str(self.engine_detection.suggested_image_root)
                self.generic_root_edit.setText(raw_root)
            if raw_root:
                try:
                    self.generic_image_root = normalize_generic_image_root(
                        self.game_root, raw_root
                    )
                    self.generic_root_edit.setText(str(self.generic_image_root))
                except Exception as exc:
                    self.status_label.setText(str(exc))
                    self.assets = []
                    self.assets_by_id = {}
                    self.filtered_assets = []
                    self._render_page()
                    self._set_actions_enabled(False)
                    return
            else:
                self.status_label.setText(
                    "Choose the folder containing loose PNG images. Scanning is read-only."
                )
                self.assets = []
                self.assets_by_id = {}
                self.filtered_assets = []
                self._render_page()
                self._set_actions_enabled(False)
                return
        self._load_key()
        self._update_profile_actions()
        self._save_project_preferences()
        self._start_scan()

    def _update_profile_actions(self) -> None:
        if self.engine_id == PROFILE_RPGMAKER_MVMZ:
            self.decrypt_selected_button.setText("Decrypt")
            self.decrypt_all_button.setText("Decrypt all")
            self.decrypt_selected_button.setToolTip(
                "Decrypt encrypted images or copy ordinary RPG Maker PNGs into the "
                "editable workspace."
            )
            self.decrypt_all_button.setToolTip(
                "Make every encrypted or ordinary RPG Maker PNG editable without "
                "overwriting existing work."
            )
        else:
            self.decrypt_selected_button.setText("Make editable")
            self.decrypt_all_button.setText("Make all editable")
            self.decrypt_selected_button.setToolTip(
                "Copy highlighted loose PNGs into the editable workspace without changing the game."
            )
            self.decrypt_all_button.setToolTip(
                "Copy every loose PNG into the editable workspace without overwriting "
                "existing work."
            )

    def _load_project(self) -> None:
        raw_path = self.folder_edit.text().strip()
        if not raw_path:
            return
        root = Path(raw_path).expanduser().resolve()
        if not root.is_dir():
            QMessageBox.warning(self, "Game Folder", f"Folder not found:\n{root}")
            return
        self.game_root = root
        self.settings.setValue("workflow/last_game_folder", str(root))
        self.selected_ids.clear()
        self._load_project_preferences()
        self._configure_engine_and_scan()

    def refresh_game_root_from_settings(self) -> None:
        """Load a game newly selected in the RPG Maker Workflow tab."""
        saved = str(self.settings.value("workflow/last_game_folder", "") or "").strip()
        if not saved:
            return
        resolved = Path(saved).expanduser().resolve()
        if resolved == self.game_root:
            return
        self.folder_edit.setText(str(resolved))
        self._load_project()

    def _load_key(self) -> None:
        if self.engine_id != PROFILE_RPGMAKER_MVMZ:
            self.key = None
            return
        try:
            self.key = read_encryption_key(self.game_root)
        except Exception:
            self.key = None

    def _start_scan(self) -> None:
        if self.game_root is None:
            return
        self._set_actions_enabled(False)
        self.status_label.setText("Scanning image folders…")
        self._scan_generation += 1
        worker = _ImageScanWorker(
            self._scan_generation,
            self.game_root,
            self.engine_id,
            self.generic_image_root,
        )
        worker.done.connect(self._scan_done)
        worker.error.connect(self._scan_error)
        worker.finished.connect(lambda w=worker: self._forget_scan_worker(w))
        self._scan_workers.append(worker)
        self._scan_worker = worker
        worker.start()

    def _forget_scan_worker(self, worker: _ImageScanWorker) -> None:
        if worker in self._scan_workers:
            self._scan_workers.remove(worker)

    def _scan_done(self, generation: int, assets: list[ImageAsset]) -> None:
        if generation != self._scan_generation:
            return
        self.assets = assets
        self.assets_by_id = {asset.asset_id: asset for asset in assets}
        self._set_actions_enabled(True)
        self.selected_ids.intersection_update(self.assets_by_id)
        self.folder_combo.blockSignals(True)
        current_folder = self.folder_combo.currentData() or ""
        self.folder_combo.clear()
        self.folder_combo.addItem("All folders", "")
        folders = sorted(
            {asset.relative_png.parent.as_posix() for asset in assets}, key=str.casefold
        )
        for folder in folders:
            self.folder_combo.addItem(folder, folder)
        index = self.folder_combo.findData(current_folder)
        self.folder_combo.setCurrentIndex(max(0, index))
        self.folder_combo.blockSignals(False)
        encrypted = sum(asset.has_encrypted for asset in assets)
        editable = sum(asset.has_plain for asset in assets)
        self.status_label.setText(
            f"{profile_label(self.engine_id)} · found {len(assets):,} images · "
            f"{encrypted:,} encrypted · "
            f"{editable:,} editable PNG copies · {len(self.selected_ids):,} highlighted"
        )
        self._update_prepare_scope()
        self._apply_filters()

    def _scan_error(self, generation: int, message: str) -> None:
        if generation != self._scan_generation:
            return
        self._set_actions_enabled(False)
        self.status_label.setText(f"Image scan failed: {message}")
        QMessageBox.critical(self, "Image Scan Failed", message)

    def _apply_filters(self) -> None:
        query = self.search_edit.text().strip().casefold()
        folder = self.folder_combo.currentData() or ""
        state = self.state_combo.currentData()
        filtered: list[ImageAsset] = []
        for asset in self.assets:
            if query and query not in asset.asset_id.casefold():
                continue
            if folder and asset.relative_png.parent.as_posix() != folder:
                continue
            if state == "editable" and not asset.has_plain:
                continue
            filtered.append(asset)
        self.filtered_assets = filtered
        self.page = 0
        self._render_page()

    def _page_assets(self) -> list[ImageAsset]:
        start = self.page * _PAGE_SIZE
        return self.filtered_assets[start:start + _PAGE_SIZE]

    def _render_page(self) -> None:
        if self._thumbnail_worker and self._thumbnail_worker.isRunning():
            self._thumbnail_worker.requestInterruption()
        page_count = max(1, (len(self.filtered_assets) + _PAGE_SIZE - 1) // _PAGE_SIZE)
        self.page = min(self.page, page_count - 1)
        page_assets = self._page_assets()
        self.image_list.blockSignals(True)
        self.image_list.clear()
        placeholder = QPixmap(112, 112)
        placeholder.fill(QColor("#292929"))
        placeholder_icon = QIcon(placeholder)
        for asset in page_assets:
            label = asset.relative_png.name
            item = QListWidgetItem(placeholder_icon, label)
            item.setData(_ASSET_ID_ROLE, asset.asset_id)
            if asset.has_encrypted and asset.has_plain:
                kind = "encrypted + editable"
            elif asset.has_encrypted:
                kind = "encrypted"
            elif asset.has_runtime_plain:
                kind = "runtime PNG"
            else:
                kind = "editable PNG"
            item.setToolTip(f"{asset.asset_id}\n{kind}")
            self.image_list.addItem(item)
            item.setSelected(asset.asset_id in self.selected_ids)
        self.image_list.blockSignals(False)
        self.page_label.setText(
            f"Page {self.page + 1} / {page_count} · {len(self.filtered_assets):,} matches"
        )
        self.previous_button.setEnabled(self.page > 0)
        self.next_button.setEnabled(self.page + 1 < page_count)
        self._thumbnail_generation += 1
        worker = _ThumbnailWorker(
            self._thumbnail_generation,
            page_assets,
            self.key,
            self.engine_id,
        )
        worker.done.connect(self._thumbnails_ready)
        worker.finished.connect(lambda w=worker: self._forget_thumbnail_worker(w))
        self._thumbnail_workers.append(worker)
        self._thumbnail_worker = worker
        worker.start()

    def _forget_thumbnail_worker(self, worker: _ThumbnailWorker) -> None:
        if worker in self._thumbnail_workers:
            self._thumbnail_workers.remove(worker)

    def _thumbnails_ready(self, generation: int, thumbnails: dict[str, bytes]) -> None:
        if generation != self._thumbnail_generation:
            return
        self.image_list.setUpdatesEnabled(False)
        try:
            for index in range(self.image_list.count()):
                item = self.image_list.item(index)
                data = thumbnails.get(item.data(_ASSET_ID_ROLE), b"")
                if not data:
                    continue
                pixmap = QPixmap()
                if pixmap.loadFromData(data, "PNG"):
                    item.setIcon(QIcon(pixmap))
            self.image_list.doItemsLayout()
        finally:
            self.image_list.setUpdatesEnabled(True)
        self.image_list.viewport().update()

    def _change_page(self, delta: int) -> None:
        self.page += delta
        self._render_page()

    def _selection_changed(self) -> None:
        page_ids = {
            self.image_list.item(index).data(_ASSET_ID_ROLE)
            for index in range(self.image_list.count())
        }
        selected_on_page = {
            item.data(_ASSET_ID_ROLE) for item in self.image_list.selectedItems()
        }
        self.selected_ids.difference_update(page_ids)
        self.selected_ids.update(selected_on_page)
        self._update_selection_status()

    def _update_selection_status(self) -> None:
        self._update_prepare_scope()
        self.status_label.setText(
            f"{len(self.filtered_assets):,} matching images · "
            f"{len(self.selected_ids):,} highlighted · "
            f"{sum(asset.has_plain for asset in self.assets):,} editable"
        )

    def _update_prepare_scope(self) -> None:
        if self.selected_ids:
            self.prepare_button.setText("Patch selected")
        else:
            self.prepare_button.setText("Patch all")

    def _show_preview(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is None:
            return
        asset = self.assets_by_id.get(current.data(_ASSET_ID_ROLE))
        if asset is None:
            return
        try:
            raw = preview_profile_png_bytes(self.engine_id, asset, self.key)
            pixmap = QPixmap()
            if not pixmap.loadFromData(raw, "PNG"):
                raise ValueError("Qt could not decode this PNG")
            self.preview_label.setPixmap(
                pixmap.scaled(
                    self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )
        except Exception as exc:
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText(f"Preview unavailable\n{exc}")
        details = [asset.asset_id]
        details.append(f"Engine: {profile_label(self.engine_id)}")
        if asset.has_encrypted:
            details.append(f"Runtime encrypted: {asset.encrypted_path}")
        elif asset.has_runtime_plain:
            details.append(f"Runtime PNG: {asset.runtime_plain_path}")
        details.append(
            f"Editable PNG: {asset.plain_path}"
            if asset.has_plain
            else f"Editable folder target: {asset.plain_path} (not created)"
        )
        details.append(
            "Highlighted: yes" if asset.asset_id in self.selected_ids
            else "Highlighted: no"
        )
        self.path_label.setText("\n".join(details))

    def _open_editable_folder(self) -> None:
        if self.game_root is None:
            return
        try:
            workspace = ensure_editable_workspace(self.game_root)
            highlighted_parents = {
                asset.plain_path.parent for asset in self._selected_assets()
            }
            if len(highlighted_parents) == 1:
                target = highlighted_parents.pop()
            else:
                root = Path(self.game_root).expanduser().resolve()
                if self.engine_id == PROFILE_GENERIC:
                    source_root = normalize_generic_image_root(
                        root, self.generic_image_root
                    )
                    source_relative = source_root.relative_to(root)
                    folder = self.folder_combo.currentData() or source_relative.as_posix()
                    relative_folder = Path(folder)
                    if relative_folder.is_absolute() or ".." in relative_folder.parts:
                        raise ValueError(f"Invalid editable image folder: {folder}")
                    target = workspace / relative_folder
                else:
                    content_relative = resolve_content_root(root).relative_to(root)
                    folder = self.folder_combo.currentData() or "img"
                    relative_folder = Path(folder)
                    if relative_folder.is_absolute() or ".." in relative_folder.parts:
                        raise ValueError(f"Invalid editable image folder: {folder}")
                    target = workspace / content_relative / relative_folder
            target.resolve().relative_to(workspace.resolve())
            target.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
                raise RuntimeError("The system file manager could not open the folder.")
            self.status_label.setText(f"Editable images: {target}")
        except Exception as exc:
            QMessageBox.warning(self, "Editable Image Folder", str(exc))

    def _editable_image_root(self) -> Path:
        if self.game_root is None:
            raise ValueError("Select a game folder first.")
        root = Path(self.game_root).expanduser().resolve()
        if self.engine_id == PROFILE_GENERIC:
            source_root = normalize_generic_image_root(root, self.generic_image_root)
            return editable_workspace_root(root) / source_root.relative_to(root)
        content_relative = resolve_content_root(root).relative_to(root)
        return editable_workspace_root(root) / content_relative / "img"

    def _copy_translation_skill(self) -> None:
        """Copy the bitmap-localization skill with paths for this project."""
        editable_assets = self._editable_assets()
        if not editable_assets:
            QMessageBox.information(
                self,
                "No Editable Images",
                "Make one or more images editable before copying the translation skill.",
            )
            return
        try:
            if self.game_root is None:
                raise ValueError("Select a game folder first.")
            game_root = Path(self.game_root).expanduser().resolve()
            profile = get_image_profile(self.engine_id)
            replacements = {
                "{{ENGINE_NAME}}": profile.label,
                "{{ENGINE_CONTEXT}}": profile.translation_skill_context,
                "{{GAME_ROOT}}": str(game_root),
                "{{EDITABLE_IMAGES_FOLDER}}": str(self._editable_image_root().resolve()),
                "{{VOCAB_FILE}}": str(game_root / "vocab.txt"),
            }
            prompt = load_clipboard_skill("image_translation.md")
            missing = [token for token in replacements if token not in prompt]
            if missing:
                raise ValueError(
                    "Image translation skill is missing required placeholder(s): "
                    + ", ".join(missing)
                )
            for token, value in replacements.items():
                prompt = prompt.replace(token, value)
            QApplication.clipboard().setText(prompt)
            self.status_label.setText(
                f"Copied image translation skill for {len(editable_assets):,} editable PNG(s): "
                f"{self._editable_image_root()}"
            )
        except Exception as exc:
            QMessageBox.warning(self, "Copy Image Translation Skill", str(exc))

    def _selected_assets(self) -> list[ImageAsset]:
        return [self.assets_by_id[key] for key in self.selected_ids if key in self.assets_by_id]

    def _editable_assets(self) -> list[ImageAsset]:
        return [asset for asset in self.assets if asset.has_plain]

    def _ensure_key(self) -> bool:
        if self.engine_id != PROFILE_RPGMAKER_MVMZ:
            return True
        if self.key is not None:
            return True
        try:
            self.key = read_encryption_key(self.game_root)
            return True
        except Exception as exc:
            QMessageBox.warning(self, "Encryption Key Not Found", str(exc))
            return False

    def _decrypt_checked(self) -> None:
        assets = [
            asset
            for asset in self._selected_assets()
            if (asset.has_encrypted or asset.has_runtime_plain) and not asset.has_plain
        ]
        if not assets:
            QMessageBox.information(
                self,
                "Nothing to Make Editable",
                "Highlight one or more runtime images that are not already editable.",
            )
            return
        needs_key = any(asset.has_encrypted for asset in assets)
        if not needs_key or self._ensure_key():
            action = "decrypt" if self.engine_id == PROFILE_RPGMAKER_MVMZ else "make_editable"
            self._start_action(action, assets)

    def _decrypt_all(self) -> None:
        assets = [
            asset
            for asset in self.assets
            if (asset.has_encrypted or asset.has_runtime_plain) and not asset.has_plain
        ]
        if not assets:
            QMessageBox.information(
                self,
                "Nothing to Make Editable",
                "All runtime images already have editable PNG copies.",
            )
            return
        verb = "Decrypt" if self.engine_id == PROFILE_RPGMAKER_MVMZ else "Make Editable"
        answer = QMessageBox.question(
            self,
            f"{verb} Every Image",
            f"Make all {len(assets):,} image(s) editable under .dazedtl/images?\n\n"
            "Existing editable copies will not be overwritten.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        needs_key = any(asset.has_encrypted for asset in assets)
        if answer == QMessageBox.Yes and (not needs_key or self._ensure_key()):
            action = "decrypt" if self.engine_id == PROFILE_RPGMAKER_MVMZ else "make_editable"
            self._start_action(action, assets)

    def _remove_highlighted(self) -> None:
        assets = [asset for asset in self._selected_assets() if asset.has_plain]
        if not assets:
            QMessageBox.information(
                self,
                "No Editable Images Highlighted",
                "Highlight one or more images from the Editable images filter first.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Remove Editable Images",
            f"Remove {len(assets):,} highlighted image(s) from the editable folder?\n\n"
            "Their editable PNG copies will be deleted. The original game images will not "
            "be changed, and encrypted images can be decrypted again later.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._start_action("remove", assets)

    def _prepare_checked(self) -> None:
        highlighted = bool(self.selected_ids)
        assets = (
            [asset for asset in self._selected_assets() if asset.has_plain]
            if highlighted
            else self._editable_assets()
        )
        if not assets:
            message = (
                "None of the highlighted images are in the editable folder. Make them "
                "editable first "
                "or clear the highlights to patch every editable image."
                if highlighted
                else "Make images editable first."
            )
            QMessageBox.information(
                self,
                "No Editable Images",
                message,
            )
            return
        if any(asset.has_encrypted for asset in assets) and not self._ensure_key():
            return
        scope = (
            f"the {len(assets):,} highlighted editable image(s)"
            if highlighted
            else f"all {len(assets):,} editable image(s)"
        )
        answer = QMessageBox.question(
            self,
            "Prepare Images for Patch",
            f"Check {scope} and add changed images to the patch?\n\n"
            "Unchanged editable copies will be skipped. Changed images will be staged and rebuilt "
            "for the active engine from .dazedtl/images. Current runtime files are backed up once "
            "under .dazedtl/image_backups. Exact allow-rules are then "
            "added to the applicable .gitignore files. Editable PNG copies will remain available "
            "for further changes until you remove them. If a runtime image changed externally, "
            "the selected batch is stopped without partially publishing it.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._start_action("prepare", assets)

    def _start_action(self, action: str, assets: list[ImageAsset]) -> None:
        self._set_actions_enabled(False)
        worker = _ImageActionWorker(
            action, self.game_root, assets, self.key, self.engine_id
        )
        worker.status.connect(self.status_label.setText)
        worker.done.connect(self._action_done)
        worker.error.connect(self._action_error)
        self._action_worker = worker
        worker.start()

    def _action_done(self, action: str, result) -> None:
        if action in {"decrypt", "make_editable"}:
            workspace = editable_workspace_root(self.game_root)
            summary = (
                f"Created {result.completed:,} editable image(s) in {workspace}; "
                f"skipped {result.skipped:,}."
            )
        elif action == "remove":
            self.selected_ids = {
                asset_id
                for asset_id in self.selected_ids
                if self.assets_by_id.get(asset_id) is not None
                and self.assets_by_id[asset_id].has_plain
            }
            summary = (
                f"Removed {result.completed:,} editable image(s); "
                f"skipped {result.skipped:,}. Runtime images were left unchanged."
            )
        else:
            summary = (
                f"Prepared {result.completed:,} image(s) for the patch and updated "
                f"{len(result.gitignore_files):,} .gitignore file(s); "
                f"skipped {result.skipped:,} unchanged image(s)."
            )
        if result.errors:
            shown = "\n".join(result.errors[:12])
            if len(result.errors) > 12:
                shown += f"\n…and {len(result.errors) - 12} more"
            QMessageBox.warning(self, "Image Action Completed with Errors", f"{summary}\n\n{shown}")
        else:
            QMessageBox.information(self, "Image Action Complete", summary)
        self.status_label.setText(summary)
        self._start_scan()

    def _action_error(self, message: str) -> None:
        self.status_label.setText(f"Image action failed: {message}")
        self._set_actions_enabled(True)
        QMessageBox.critical(self, "Image Action Failed", message)

    def _set_actions_enabled(self, enabled: bool) -> None:
        for button in (
            self.open_workspace_button,
            self.copy_translation_button,
            self.decrypt_selected_button,
            self.decrypt_all_button,
            self.remove_button,
            self.prepare_button,
        ):
            button.setEnabled(enabled)
        self.copy_translation_button.setEnabled(enabled and bool(self._editable_assets()))

    def closeEvent(self, event) -> None:
        running = [
            worker for worker in (
                *self._scan_workers, *self._thumbnail_workers, self._action_worker
            )
            if worker is not None and worker.isRunning()
        ]
        action_running = self._action_worker is not None and self._action_worker.isRunning()
        if action_running:
            QMessageBox.information(
                self, "Image Action Running", "Wait for the current image action to finish."
            )
            event.ignore()
            return
        for worker in running:
            worker.requestInterruption()
            worker.wait(1000)
        if any(worker.isRunning() for worker in running):
            self.status_label.setText("Finishing image scan/preview before closing…")
            event.ignore()
            return
        super().closeEvent(event)


# Backward-compatible import for callers and third-party scripts using the old name.
RPGMakerImageManager = ImageManager
