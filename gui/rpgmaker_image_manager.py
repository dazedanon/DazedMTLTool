"""Visual RPG Maker MV/MZ image decrypt/encrypt and patch manager."""

from __future__ import annotations

from pathlib import Path

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

from util.rpgmaker_images import (
    ImageAsset,
    clean_runtime_image_duplicates,
    decrypt_assets,
    editable_workspace_root,
    ensure_editable_workspace,
    migrate_legacy_editable_workspace,
    prepare_assets_for_patch,
    preview_png_bytes,
    read_encryption_key,
    remove_editable_assets,
    resolve_content_root,
    scan_image_assets,
    thumbnail_png_bytes,
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

    def __init__(self, generation: int, game_root: Path):
        super().__init__()
        self.generation = generation
        self.game_root = game_root

    def run(self) -> None:
        try:
            self.done.emit(self.generation, scan_image_assets(self.game_root))
        except Exception as exc:
            self.error.emit(self.generation, str(exc))


class _ThumbnailWorker(QThread):
    done = pyqtSignal(int, object)

    def __init__(self, generation: int, assets: list[ImageAsset], key: bytes | None):
        super().__init__()
        self.generation = generation
        self.assets = assets
        self.key = key

    def run(self) -> None:
        thumbnails: dict[str, bytes] = {}
        for asset in self.assets:
            if self.isInterruptionRequested():
                return
            try:
                data = thumbnail_png_bytes(asset, self.key, size=112)
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
    ):
        super().__init__()
        self.action = action
        self.game_root = game_root
        self.assets = assets
        self.key = key

    def run(self) -> None:
        try:
            if self.action == "decrypt":
                result = decrypt_assets(
                    self.assets,
                    self.key,
                    game_root=self.game_root,
                    overwrite=False,
                    progress=self.status.emit,
                )
            elif self.action == "remove":
                result = remove_editable_assets(
                    self.game_root, self.assets, progress=self.status.emit
                )
            else:
                result = prepare_assets_for_patch(
                    self.game_root, self.assets, self.key, progress=self.status.emit
                )
            self.done.emit(self.action, result)
        except Exception as exc:
            self.error.emit(str(exc))


class RPGMakerImageManager(QWidget):
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
            self.status_label.setText("Select an RPG Maker MV/MZ game folder to begin.")
            self._set_actions_enabled(False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 12)
        title = QLabel("RPG Maker MV/MZ Image Manager")
        title.setStyleSheet("font-size:18px;font-weight:bold;color:#e0e0e0;")
        root.addWidget(title)
        intro = QLabel(
            "Select images while browsing, decrypt them into .dazedtl/images, edit the PNGs, "
            "then highlight the finished images to patch only those, or clear highlights to "
            "patch every editable image. "
            "Pages keep very large games responsive."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#b8b8b8;font-size:13px;padding:2px 0 6px 0;")
        root.addWidget(intro)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Game folder:"))
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Select an RPG Maker MV/MZ game folder…")
        self.folder_edit.returnPressed.connect(self._load_project)
        folder_row.addWidget(self.folder_edit, 1)
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._browse_game_root)
        folder_row.addWidget(browse_button)
        load_button = QPushButton("Load")
        load_button.clicked.connect(self._load_project)
        folder_row.addWidget(load_button)
        root.addLayout(folder_row)

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
        folder = QFileDialog.getExistingDirectory(self, "Select RPG Maker Game Folder", start)
        if folder:
            self.folder_edit.setText(folder)
            self._load_project()

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
        try:
            migrate_legacy_editable_workspace(root)
            clean_runtime_image_duplicates(root)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Editable Image Cleanup",
                f"Could not consolidate editable images under .dazedtl:\n{exc}",
            )
        self.selected_ids.clear()
        self._load_key()
        self._start_scan()

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
        worker = _ImageScanWorker(self._scan_generation, self.game_root)
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
            f"Found {len(assets):,} images · {encrypted:,} encrypted · "
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
        worker = _ThumbnailWorker(self._thumbnail_generation, page_assets, self.key)
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
            raw = preview_png_bytes(asset, self.key)
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
        content_relative = resolve_content_root(root).relative_to(root)
        return editable_workspace_root(root) / content_relative / "img"

    def _copy_translation_skill(self) -> None:
        """Copy the bitmap-localization skill with paths for this project."""
        editable_assets = self._editable_assets()
        if not editable_assets:
            QMessageBox.information(
                self,
                "No Editable Images",
                "Decrypt one or more images before copying the translation skill.",
            )
            return
        try:
            if self.game_root is None:
                raise ValueError("Select a game folder first.")
            game_root = Path(self.game_root).expanduser().resolve()
            replacements = {
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
            if asset.has_encrypted and not asset.has_plain
        ]
        if not assets:
            QMessageBox.information(
                self,
                "Nothing to Decrypt",
                "Highlight one or more encrypted images that are not already editable.",
            )
            return
        if self._ensure_key():
            self._start_action("decrypt", assets)

    def _decrypt_all(self) -> None:
        assets = [asset for asset in self.assets if asset.has_encrypted and not asset.has_plain]
        if not assets:
            QMessageBox.information(self, "Nothing to Decrypt", "All encrypted images already have PNG copies.")
            return
        answer = QMessageBox.question(
            self,
            "Decrypt Every Image",
            f"Decrypt all {len(assets):,} encrypted image(s) into .dazedtl/images?\n\n"
            "Existing editable copies will not be overwritten.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes and self._ensure_key():
            self._start_action("decrypt", assets)

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
                "None of the highlighted images are in the editable folder. Decrypt them first "
                "or clear the highlights to patch every editable image."
                if highlighted
                else "Decrypt images into the editable folder first."
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
            "Unchanged editable copies will be skipped. Changed encrypted images will be rebuilt "
            "from .dazedtl/images. Their original encrypted "
            "files are backed up once under .dazedtl/image_backups. Exact allow-rules are then "
            "added to the applicable .gitignore files. Editable PNG copies will remain available "
            "for further changes until you remove them.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._start_action("prepare", assets)

    def _start_action(self, action: str, assets: list[ImageAsset]) -> None:
        self._set_actions_enabled(False)
        worker = _ImageActionWorker(action, self.game_root, assets, self.key)
        worker.status.connect(self.status_label.setText)
        worker.done.connect(self._action_done)
        worker.error.connect(self._action_error)
        self._action_worker = worker
        worker.start()

    def _action_done(self, action: str, result) -> None:
        if action == "decrypt":
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
