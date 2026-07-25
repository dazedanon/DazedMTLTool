"""Visual RPG Maker MV/MZ image decrypt/encrypt and patch manager."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt, QSize, QThread, pyqtSignal, QSettings
from PyQt5.QtGui import QColor, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from util.paths import APP_NAME, ORG_NAME

from util.rpgmaker_images import (
    ImageAsset,
    decrypt_assets,
    encrypt_assets,
    prepare_assets_for_patch,
    preview_png_bytes,
    read_encryption_key,
    scan_image_assets,
    thumbnail_png_bytes,
)


_ASSET_ID_ROLE = Qt.UserRole + 1
_PAGE_SIZE = 80


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
                    self.assets, self.key, overwrite=False, progress=self.status.emit
                )
            elif self.action == "encrypt":
                result = encrypt_assets(
                    self.game_root, self.assets, self.key, progress=self.status.emit
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
            "Browse encrypted images visually, create editable PNG copies, then select only "
            "the translated images you want in the patch. Pages keep very large games responsive."
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
        self.folder_combo = QComboBox()
        self.folder_combo.addItem("All folders", "")
        self.folder_combo.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self.folder_combo, 1)
        self.state_combo = QComboBox()
        self.state_combo.addItem("All images", "all")
        self.state_combo.addItem("Encrypted", "encrypted")
        self.state_combo.addItem("Editable PNG ready", "plain")
        self.state_combo.addItem("Unencrypted PNG", "plain_only")
        self.state_combo.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self.state_combo)
        root.addLayout(filters)

        splitter = QSplitter(Qt.Horizontal)
        self.image_list = QListWidget()
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
        self.image_list.itemSelectionChanged.connect(self._selection_changed)
        self.image_list.currentItemChanged.connect(self._show_preview)
        self.image_list.setToolTip(
            "Select images normally. Ctrl-click toggles individual images, Shift-click selects "
            "a range, and Ctrl+A selects the current page."
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

        page_row = QHBoxLayout()
        select_page = QPushButton("Select page")
        select_page.clicked.connect(self._select_page)
        page_row.addWidget(select_page)
        clear_selection = QPushButton("Clear selection")
        clear_selection.clicked.connect(self._clear_selection)
        page_row.addWidget(clear_selection)
        page_row.addStretch()
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
        root.addLayout(page_row)

        action_row = QHBoxLayout()
        self.decrypt_selected_button = QPushButton("Decrypt selected")
        self.decrypt_selected_button.clicked.connect(self._decrypt_checked)
        action_row.addWidget(self.decrypt_selected_button)
        self.decrypt_all_button = QPushButton("Decrypt all encrypted")
        self.decrypt_all_button.clicked.connect(self._decrypt_all)
        action_row.addWidget(self.decrypt_all_button)
        self.encrypt_button = QPushButton("Encrypt selected")
        self.encrypt_button.setToolTip(
            "Rebuild selected encrypted runtime files from their editable PNG copies."
        )
        self.encrypt_button.clicked.connect(self._encrypt_checked)
        action_row.addWidget(self.encrypt_button)
        self.prepare_button = QPushButton("Encrypt + patch selected")
        self.prepare_button.setStyleSheet(
            "QPushButton{border:1px solid #4ec9b0;color:#4ec9b0;font-weight:bold;padding:6px 14px;}"
            "QPushButton:hover{background:#18352f;}"
        )
        self.prepare_button.setToolTip(
            "Re-encrypt selected edited PNGs, preserve original encrypted files in "
            ".dazedtl/image_backups, and add exact .gitignore allow-rules."
        )
        self.prepare_button.clicked.connect(self._prepare_checked)
        action_row.addWidget(self.prepare_button)
        action_row.addStretch()
        root.addLayout(action_row)

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
        self._set_actions_enabled(True)
        self.assets = assets
        self.assets_by_id = {asset.asset_id: asset for asset in assets}
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
        editable = sum(asset.has_plain and asset.has_encrypted for asset in assets)
        self.status_label.setText(
            f"Found {len(assets):,} images · {encrypted:,} encrypted · "
            f"{editable:,} editable PNG copies · {len(self.selected_ids):,} selected"
        )
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
            if state == "encrypted" and not asset.has_encrypted:
                continue
            if state == "plain" and not (asset.has_plain and asset.has_encrypted):
                continue
            if state == "plain_only" and not (asset.has_plain and not asset.has_encrypted):
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
            kind = "encrypted + PNG" if asset.has_encrypted and asset.has_plain else (
                "encrypted" if asset.has_encrypted else "PNG"
            )
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

    def _select_page(self) -> None:
        self.image_list.blockSignals(True)
        for index in range(self.image_list.count()):
            item = self.image_list.item(index)
            item.setSelected(True)
            self.selected_ids.add(item.data(_ASSET_ID_ROLE))
        self.image_list.blockSignals(False)
        self._update_selection_status()

    def _clear_selection(self) -> None:
        self.selected_ids.clear()
        self.image_list.clearSelection()
        self._update_selection_status()

    def _update_selection_status(self) -> None:
        self.status_label.setText(
            f"{len(self.filtered_assets):,} matching images · {len(self.selected_ids):,} selected"
        )

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
            details.append(f"Encrypted: {asset.encrypted_path.name}")
        details.append("Editable PNG: ready" if asset.has_plain else "Editable PNG: not decrypted")
        self.path_label.setText("\n".join(details))

    def _selected_assets(self) -> list[ImageAsset]:
        return [self.assets_by_id[key] for key in self.selected_ids if key in self.assets_by_id]

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
        assets = [asset for asset in self._selected_assets() if asset.has_encrypted]
        if not assets:
            QMessageBox.information(
                self, "Nothing Selected", "Select one or more encrypted images first."
            )
            return
        if self._ensure_key():
            self._start_action("decrypt", assets)

    def _decrypt_all(self) -> None:
        assets = [asset for asset in self.assets if asset.has_encrypted and not asset.has_plain]
        if not assets:
            QMessageBox.information(self, "Nothing to Decrypt", "All encrypted images already have PNG copies.")
            return
        if self._ensure_key():
            self._start_action("decrypt", assets)

    def _prepare_checked(self) -> None:
        assets = self._selected_assets()
        if not assets:
            QMessageBox.information(
                self, "Nothing Selected", "Select the translated images to include first."
            )
            return
        if any(asset.has_encrypted for asset in assets) and not self._ensure_key():
            return
        answer = QMessageBox.question(
            self,
            "Prepare Images for Patch",
            f"Prepare exactly {len(assets):,} selected image(s)?\n\n"
            "Encrypted images will be rebuilt from their editable PNG. Their original encrypted "
            "files are backed up once under .dazedtl/image_backups. Exact allow-rules are then "
            "added to the applicable .gitignore files.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._start_action("prepare", assets)

    def _encrypt_checked(self) -> None:
        assets = [
            asset for asset in self._selected_assets()
            if asset.has_encrypted and asset.has_plain
        ]
        if not assets:
            QMessageBox.information(
                self, "Nothing Ready", "Select images with editable PNG copies first."
            )
            return
        if not self._ensure_key():
            return
        answer = QMessageBox.question(
            self,
            "Encrypt Images",
            f"Rebuild {len(assets):,} selected encrypted image(s) from their PNG copies?\n\n"
            "Original encrypted files are backed up once under .dazedtl/image_backups.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._start_action("encrypt", assets)

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
            summary = f"Decrypted {result.completed:,} image(s); skipped {result.skipped:,}."
        elif action == "encrypt":
            summary = f"Encrypted {result.completed:,} image(s)."
        else:
            summary = (
                f"Prepared {result.completed:,} image(s) for the patch and updated "
                f"{len(result.gitignore_files):,} .gitignore file(s)."
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
            self.decrypt_selected_button,
            self.decrypt_all_button,
            self.encrypt_button,
            self.prepare_button,
        ):
            button.setEnabled(enabled)

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
                self, "Image Action Running", "Wait for the current decrypt/encrypt action to finish."
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
