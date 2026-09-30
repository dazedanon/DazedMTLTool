"""Engine-aware visual image workspace and patch manager."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from PyQt5.QtCore import (
    QEvent,
    QItemSelectionModel,
    QPoint,
    Qt,
    QSize,
    QThread,
    pyqtSignal,
    QSettings,
    QTimer,
    QUrl,
)
from PyQt5.QtGui import QColor, QDesktopServices, QIcon, QPixmap, QStandardItem
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QListView,
    QMessageBox,
    QPushButton,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from util.paths import (
    APP_NAME,
    ORG_NAME,
    PROJECT_ROOT,
    prepare_game_translation_context,
)
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
from gui.theme import COLORS, Geometry, Spacing
from gui.workflow_components import StatusBanner
from gui.ui_components import (
    PageHeader,
    SectionCard,
    action_button_width_hint,
    configure_action_button,
    equalize_button_widths,
    make_page_layout,
    set_status_text,
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


class _MultiFolderComboBox(_BoundedComboBox):
    """Checkable folder filter with standard plain/Ctrl/Shift selection."""

    foldersChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selection_anchor_row = -1
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().installEventFilter(self)
        self.view().setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view().installEventFilter(self)
        self.view().viewport().installEventFilter(self)
        self.setAccessibleName("Image folders")
        self.set_folders(())

    def selected_folders(self) -> set[str]:
        selected: set[str] = set()
        model = self.model()
        for row in range(1, model.rowCount()):
            item = model.item(row)
            if item is not None and item.checkState() == Qt.Checked:
                selected.add(str(item.data(Qt.UserRole)))
        return selected

    def set_folders(
        self, folders, selected: set[str] | None = None
    ) -> None:
        selected = set(selected or ())
        self.clear()
        all_item = QStandardItem("All folders")
        all_item.setCheckable(True)
        all_item.setEditable(False)
        all_item.setData("", Qt.UserRole)
        self.model().appendRow(all_item)
        for folder in folders:
            item = QStandardItem(folder)
            item.setCheckable(True)
            item.setEditable(False)
            item.setData(folder, Qt.UserRole)
            self.model().appendRow(item)
        available = {
            str(self.model().item(row).data(Qt.UserRole))
            for row in range(1, self.model().rowCount())
        }
        self._selection_anchor_row = -1
        self.set_selected_folders(selected & available, emit=False)

    def set_selected_folders(
        self, folders: set[str], *, emit: bool = True
    ) -> None:
        selected = set(folders)
        model = self.model()
        for row in range(model.rowCount()):
            item = model.item(row)
            if item is None:
                continue
            checked = row == 0 and not selected
            if row > 0:
                checked = str(item.data(Qt.UserRole)) in selected
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self._sync_view_selection()
        self._update_summary()
        if emit:
            self.foldersChanged.emit()

    def _sync_view_selection(self) -> None:
        selection = self.view().selectionModel()
        selection.clearSelection()
        model = self.model()
        for row in range(model.rowCount()):
            item = model.item(row)
            if item is None or item.checkState() != Qt.Checked:
                continue
            selection.select(
                model.index(row, 0),
                QItemSelectionModel.Select | QItemSelectionModel.Rows,
            )

    def _update_summary(self) -> None:
        selected = sorted(self.selected_folders(), key=str.casefold)
        if not selected:
            summary = "All folders"
        elif len(selected) == 1:
            summary = selected[0]
        else:
            summary = f"{len(selected):,} folders selected"
        super().setCurrentIndex(0)
        self.lineEdit().setText(summary)
        self.lineEdit().setCursorPosition(0)
        self.setToolTip(
            "Click selects one folder; Ctrl-click toggles folders; "
            "Shift-click selects a range.\n\n"
            + ("\n".join(selected) if selected else "All folders")
        )

    def showPopup(self) -> None:
        super().showPopup()
        self._sync_view_selection()

    def _select_row(self, row: int, modifiers) -> None:
        model = self.model()
        if not 0 <= row < model.rowCount():
            return
        if row == 0:
            self._selection_anchor_row = -1
            self.set_selected_folders(set())
            return

        folder = str(model.item(row).data(Qt.UserRole))
        selected = self.selected_folders()
        shift = bool(modifiers & Qt.ShiftModifier)
        control = bool(modifiers & Qt.ControlModifier)
        if shift:
            anchor = self._selection_anchor_row
            if not 1 <= anchor < model.rowCount():
                anchor = row
            if not control:
                selected.clear()
            first, last = sorted((anchor, row))
            selected.update(
                str(model.item(index).data(Qt.UserRole))
                for index in range(first, last + 1)
            )
        elif control:
            if folder in selected:
                selected.remove(folder)
            else:
                selected.add(folder)
            self._selection_anchor_row = row
        else:
            selected = {folder}
            self._selection_anchor_row = row
        self.set_selected_folders(selected)

    def _move_folder_selection(self, direction: int) -> None:
        """Select the adjacent folder and immediately refresh its image filter."""
        model = self.model()
        if model.rowCount() <= 0:
            return
        checked_rows = [
            row
            for row in range(model.rowCount())
            if model.item(row) is not None
            and model.item(row).checkState() == Qt.Checked
        ]
        if len(checked_rows) == 1:
            current_row = checked_rows[0]
        else:
            current = self.view().currentIndex()
            current_row = current.row() if current.isValid() else 0
        target_row = max(0, min(model.rowCount() - 1, current_row + direction))
        if target_row != current_row:
            self._select_row(target_row, Qt.NoModifier)
        self.view().setCurrentIndex(model.index(target_row, 0))

    def keyPressEvent(self, event) -> None:
        blocked_modifiers = (
            Qt.ControlModifier
            | Qt.ShiftModifier
            | Qt.AltModifier
            | Qt.MetaModifier
        )
        if (
            event.key() in (Qt.Key_Up, Qt.Key_Down)
            and not event.modifiers() & blocked_modifiers
        ):
            self._move_folder_selection(1 if event.key() == Qt.Key_Down else -1)
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.lineEdit() and event.type() in (
            QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease,
        ):
            if event.button() != Qt.LeftButton:
                return super().eventFilter(watched, event)
            if event.type() == QEvent.MouseButtonPress:
                return True
            self.showPopup()
            return True
        if watched is self.view() and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Up, Qt.Key_Down):
                blocked_modifiers = (
                    Qt.ControlModifier
                    | Qt.ShiftModifier
                    | Qt.AltModifier
                    | Qt.MetaModifier
                )
                if not event.modifiers() & blocked_modifiers:
                    self._move_folder_selection(
                        1 if event.key() == Qt.Key_Down else -1
                    )
                    return True
        if watched is self.view().viewport():
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                index = self.view().indexAt(event.pos())
                if index.isValid():
                    self._select_row(index.row(), event.modifiers())
                return True
            if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                return True
        return super().eventFilter(watched, event)


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
        self._preview_pixmap: QPixmap | None = None

        self._build_ui()
        if self.game_root:
            self.folder_edit.setText(str(self.game_root))
            self._load_project()
        else:
            set_status_text(self.status_label, "Select a game folder to begin.")
            self._set_actions_enabled(False)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.page_scroll = QScrollArea()
        self.page_scroll.setObjectName("imageManagerScroll")
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.NoFrame)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.page_scroll.viewport().installEventFilter(self)
        self.page_content = QWidget()
        self.page_content.setObjectName("appPage")
        root = make_page_layout(self.page_content)
        self.page_layout = root
        self.page_scroll.setWidget(self.page_content)
        outer.addWidget(self.page_scroll)
        root.addWidget(PageHeader(
            "Image Manager",
            "Make game images editable, translate the working copies, and patch reviewed images back into the game."
        ))

        # The page header already names this single, dominant workspace. Keep
        # the card surface and padding without spending vertical space on a
        # redundant second heading.
        workspace_card = SectionCard(compact=True)
        self.workspace_card = workspace_card
        workspace_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(workspace_card, 1)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(Spacing.SM)
        folder_label = QLabel("Game folder")
        folder_row.addWidget(folder_label)
        self.folder_edit = QLineEdit()
        self.folder_edit.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.folder_edit.setPlaceholderText("Select a game folder…")
        self.folder_edit.returnPressed.connect(self._load_project)
        folder_row.addWidget(self.folder_edit, 1)
        browse_button = QPushButton("Choose…")
        configure_action_button(browse_button, variant="secondary")
        browse_button.clicked.connect(self._browse_game_root)
        folder_row.addWidget(browse_button)
        load_button = QPushButton("Load images")
        configure_action_button(load_button, variant="primary")
        load_button.clicked.connect(self._load_project)
        folder_row.addWidget(load_button)
        workspace_card.add_layout(folder_row)

        engine_row = QHBoxLayout()
        engine_row.setSpacing(Spacing.SM)
        engine_label = QLabel("Engine")
        engine_row.addWidget(engine_label)
        source_label_width = max(
            Geometry.FORM_LABEL,
            folder_label.sizeHint().width(),
            engine_label.sizeHint().width(),
        )
        folder_label.setMinimumWidth(source_label_width)
        engine_label.setMinimumWidth(source_label_width)
        self.engine_combo = QComboBox()
        self.engine_combo.setMinimumWidth(220)
        self.engine_combo.setMaximumWidth(320)
        self.engine_combo.addItem("Auto-detect", PROFILE_AUTO)
        for profile in registered_image_profiles():
            self.engine_combo.addItem(profile.label, profile.engine_id)
        self.engine_combo.currentIndexChanged.connect(self._engine_changed)
        engine_row.addWidget(self.engine_combo)
        self.engine_detection_label = QLabel(
            "Select a game folder to detect its image layout."
        )
        self.engine_detection_label.setWordWrap(True)
        self.engine_detection_label.setObjectName("appSectionDescription")
        self.engine_detection_label.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred
        )
        engine_row.addWidget(self.engine_detection_label, 1)
        self.migrate_legacy_button = QPushButton("Migrate old workspace")
        configure_action_button(self.migrate_legacy_button, variant="secondary")
        self.migrate_legacy_button.setToolTip(
            "Move images from the former DazedTL_Images folder into .dazedtl/images."
        )
        self.migrate_legacy_button.clicked.connect(self._migrate_legacy_workspace)
        self.migrate_legacy_button.hide()
        engine_row.addWidget(self.migrate_legacy_button)
        workspace_card.add_layout(engine_row)

        self.generic_root_host = QWidget()
        generic_root_row = QHBoxLayout(self.generic_root_host)
        generic_root_row.setContentsMargins(0, 0, 0, 0)
        generic_root_row.addWidget(QLabel("Image folder:"))
        self.generic_root_edit = QLineEdit()
        self.generic_root_edit.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.generic_root_edit.setPlaceholderText(
            "Choose the folder containing loose PNG images…"
        )
        self.generic_root_edit.returnPressed.connect(self._generic_root_changed)
        generic_root_row.addWidget(self.generic_root_edit, 1)
        self.generic_root_button = QPushButton("Choose…")
        configure_action_button(self.generic_root_button, variant="secondary")
        self.generic_root_button.clicked.connect(self._browse_generic_root)
        generic_root_row.addWidget(self.generic_root_button)
        workspace_card.add_widget(self.generic_root_host)
        self.generic_root_host.hide()

        filters = QHBoxLayout()
        filters.setSpacing(Spacing.SM)
        self.search_edit = QLineEdit()
        self.search_edit.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.search_edit.setPlaceholderText("Filter by any part of the folder or filename…")
        self.search_edit.textChanged.connect(self._apply_filters)
        filters.addWidget(self.search_edit, 2)
        self.folder_combo = _MultiFolderComboBox()
        self.folder_combo.setMinimumWidth(220)
        self.folder_combo.setMaximumWidth(360)
        self.folder_combo.foldersChanged.connect(self._apply_filters)
        filters.addWidget(self.folder_combo, 1)
        self.state_combo = QComboBox()
        self.state_combo.setMinimumWidth(150)
        self.state_combo.setMaximumWidth(220)
        self.state_combo.addItem("All images", "all")
        self.state_combo.addItem("Editable images", "editable")
        self.state_combo.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self.state_combo)
        workspace_card.add_layout(filters)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("imageBrowserSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(Spacing.MD)
        splitter.setStyleSheet(
            "QSplitter#imageBrowserSplitter::handle {"
            "background: transparent; border: none; }"
            f"QSplitter#imageBrowserSplitter::handle:hover {{"
            f"background: {COLORS.surface_hover}; }}"
        )
        self.browser_splitter = splitter

        self.browser_host = QWidget()
        self.browser_host.setObjectName("imageBrowserPane")
        self.browser_host.setStyleSheet(
            "QWidget#imageBrowserPane { background: transparent; border: none; }"
        )
        self.browser_host.setMinimumWidth(420)
        browser_layout = QVBoxLayout(self.browser_host)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        browser_layout.setSpacing(Spacing.SM)
        self.image_list = _UserSelectionList()
        self.image_list.setViewMode(QListWidget.IconMode)
        self.image_list.setResizeMode(QListWidget.Adjust)
        self.image_list.setMovement(QListWidget.Static)
        self.image_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.image_list.setIconSize(QSize(112, 112))
        thumbnail_text_height = self.image_list.fontMetrics().height()
        thumbnail_grid_size = QSize(
            168, max(160, 112 + thumbnail_text_height + Spacing.XL)
        )
        self.image_list.setGridSize(thumbnail_grid_size)
        # QListView otherwise derives the item rectangle from each loaded
        # pixmap's aspect ratio. Wide, short images can then leave no painted
        # text row even though the surrounding layout grid is tall enough.
        self._thumbnail_item_size = QSize(
            thumbnail_grid_size.width() - Spacing.SM,
            thumbnail_grid_size.height() - Spacing.SM,
        )
        self.image_list.setUniformItemSizes(True)
        self.image_list.setWordWrap(False)
        self.image_list.setTextElideMode(Qt.ElideMiddle)
        self.image_list.setSpacing(Spacing.SM)
        self.image_list.setObjectName("rpgImageList")
        self.image_list.setStyleSheet(
            f"QListWidget#rpgImageList{{background:{COLORS.canvas};color:{COLORS.text_primary};"
            f"border:1px solid {COLORS.border};padding:4px;outline:none;}}"
            "QListWidget#rpgImageList::item{border:1px solid transparent;"
            "padding:4px;background:transparent;}"
            f"QListWidget#rpgImageList::item:selected{{background:{COLORS.selection};"
            f"border-color:{COLORS.accent_text};color:{COLORS.on_accent};}}"
            f"QListWidget#rpgImageList::item:hover:!selected{{background:{COLORS.surface_hover};"
            f"border-color:{COLORS.border_strong};}}"
        )
        self.image_list.userSelectionChanged.connect(self._selection_changed)
        self.image_list.deleteRequested.connect(self._remove_highlighted)
        self.image_list.currentItemChanged.connect(self._show_preview)
        self.image_list.setToolTip(
            "Click highlights one image. Ctrl-click toggles individual images, Shift-click "
            "selects a range, and Ctrl+A highlights the current page. Changing a filter "
            "or page clears highlights."
        )
        browser_layout.addWidget(self.image_list, 1)

        page_row = QHBoxLayout()
        # Pagination belongs to the browser, but it must not visually merge
        # with the browser's lower edge at large application font scales.
        page_row.setContentsMargins(0, 0, 0, Spacing.SM)
        page_row.setSpacing(Spacing.SM)
        page_row.addStretch()
        self.previous_button = QPushButton("← Previous")
        configure_action_button(self.previous_button, variant="quiet")
        self.previous_button.clicked.connect(lambda: self._change_page(-1))
        page_row.addWidget(self.previous_button)
        self.page_label = QLabel("Page 0 / 0")
        self.page_label.setAlignment(Qt.AlignCenter)
        page_row.addWidget(self.page_label)
        self.next_button = QPushButton("Next →")
        configure_action_button(self.next_button, variant="quiet")
        self.next_button.clicked.connect(lambda: self._change_page(1))
        page_row.addWidget(self.next_button)
        page_row.addStretch()
        for button in (self.previous_button, self.next_button):
            button.setProperty("appRequiredParentInset", Spacing.SM)
        equalize_button_widths(
            (self.previous_button, self.next_button), minimum=0
        )
        browser_layout.addLayout(page_row)
        splitter.addWidget(self.browser_host)

        self.preview_host = QWidget()
        self.preview_host.setObjectName("imagePreviewPane")
        self.preview_host.setMinimumWidth(400)
        preview_layout = QVBoxLayout(self.preview_host)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(Spacing.SM)
        self.preview_label = QLabel("Select an image to preview it")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setWordWrap(True)
        self.preview_label.setMinimumSize(360, 240)
        self.preview_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self.preview_label.setStyleSheet(
            f"background:{COLORS.canvas};border:1px solid {COLORS.border};"
            f"color:{COLORS.text_disabled};"
        )
        preview_layout.addWidget(self.preview_label, 1)
        self.path_label = QLabel()
        self.path_label.setObjectName("imagePreviewDetails")
        self.path_label.setAccessibleName("Selected image details")
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.path_label.setWordWrap(True)
        self.path_label.setMargin(Spacing.MD)
        self.path_label.setMaximumHeight(Geometry.CONTROL * 3)
        self.path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.path_label.setStyleSheet(
            f"QLabel#imagePreviewDetails{{background:{COLORS.surface_1};"
            f"border:1px solid {COLORS.border};color:{COLORS.text_secondary};"
            f"border-radius:{Geometry.RADIUS_CONTROL}px;}}"
        )
        self.path_label.hide()
        preview_layout.addWidget(self.path_label)
        splitter.addWidget(self.preview_host)
        splitter.setSizes([700, 540])
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.splitterMoved.connect(lambda *_args: self._render_preview_pixmap())
        workspace_card.add_widget(splitter, 1)

        action_host = QWidget()
        action_host.setObjectName("imageActionBar")
        action_host.setStyleSheet(
            "QWidget#imageActionBar { background: transparent; border: none; }"
        )
        action_row = QGridLayout(action_host)
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setHorizontalSpacing(Spacing.SM)
        action_row.setVerticalSpacing(Spacing.SM)
        self.action_host = action_host
        self.action_layout = action_row
        self.open_workspace_button = QPushButton("Open folder")
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
        self.edit_text_button = QPushButton("Edit text…")
        self.edit_text_button.setToolTip(
            "Semi-manual workflow: read every editable PNG with OCR, confirm the boxes and "
            "the text, translate through DazedTL's own engine, then erase the original "
            "glyphs and draw the translation in their place. No coding agent involved."
        )
        self.edit_text_button.clicked.connect(self._open_text_editor)
        self.decrypt_selected_button = QPushButton("Make selected")
        self.decrypt_selected_button.clicked.connect(self._decrypt_checked)
        self.decrypt_all_button = QPushButton("Make all")
        self.decrypt_all_button.clicked.connect(self._decrypt_all)
        self.remove_button = QPushButton("Remove copies")
        self.remove_button.setToolTip(
            "Delete highlighted PNG copies from the editable folder. Runtime images remain "
            "untouched and can be decrypted again. The Delete key does the same thing."
        )
        self.remove_button.clicked.connect(self._remove_highlighted)
        self.prepare_button = QPushButton("Patch all")
        self.prepare_button.setToolTip(
            "With highlighted images, patch only their editable PNGs. With no highlights, patch "
            "every editable PNG. Editable copies remain in .dazedtl/images until removed."
        )
        self.prepare_button.clicked.connect(self._prepare_checked)
        action_buttons = (
            self.open_workspace_button,
            self.copy_translation_button,
            self.edit_text_button,
            self.decrypt_selected_button,
            self.decrypt_all_button,
            self.remove_button,
            self.prepare_button,
        )
        self.action_buttons = action_buttons
        for button in action_buttons:
            if button is self.prepare_button:
                variant = "primary"
            elif button is self.remove_button:
                variant = "danger"
            else:
                variant = "secondary"
            configure_action_button(button, variant=variant)
            button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._action_layout_mode = None
        self.copy_skill_help_banner = StatusBanner(
            "How to use Copy skill: first make one or more images editable. Then click Copy "
            "skill, paste the copied instructions into your AI helper with the game folder "
            "open, and review every edited image before patching it back into the game.",
            "info",
        )
        workspace_card.add_widget(self.copy_skill_help_banner)
        workspace_card.add_widget(action_host)
        self._arrange_action_bar()

        self.status_label = QLabel("Scanning image folders…")
        self.status_label.setWordWrap(True)
        set_status_text(self.status_label, "Scanning image folders…", "info")
        workspace_card.add_widget(self.status_label)

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
        set_status_text(
            self.status_label, f"Migrated {moved:,} legacy editable image(s).", "success"
        )
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
            set_status_text(self.status_label, f"Engine detection failed: {exc}", "error")
            self._set_actions_enabled(False)
            return
        self.engine_id = (
            self.engine_detection.engine_id if selected == PROFILE_AUTO else selected
        )
        image_location = ""
        if self.engine_detection.suggested_image_root is not None:
            try:
                relative_root = self.engine_detection.suggested_image_root.relative_to(
                    self.game_root
                )
                image_location = f" · Images: {relative_root.as_posix()}"
            except ValueError:
                image_location = ""
        if selected == PROFILE_AUTO:
            detected = profile_label(self.engine_id)
            confidence = (
                "fallback detection"
                if self.engine_detection.confidence == "fallback"
                else f"{self.engine_detection.confidence} confidence"
            )
            self.engine_detection_label.setText(
                f"Auto-detected {detected} · {confidence}{image_location}"
            )
        else:
            self.engine_detection_label.setText(
                f"Using {profile_label(self.engine_id)} · auto-detected "
                f"{profile_label(self.engine_detection.engine_id)}{image_location}"
            )
        self.engine_detection_label.setToolTip(self.engine_detection.reason)

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
                    set_status_text(self.status_label, str(exc), "error")
                    self.assets = []
                    self.assets_by_id = {}
                    self.filtered_assets = []
                    self._render_page()
                    self._set_actions_enabled(False)
                    return
            else:
                set_status_text(
                    self.status_label,
                    "Choose the folder containing loose PNG images. Scanning is read-only.",
                    "warning",
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
            self.decrypt_selected_button.setText("Make selected")
            self.decrypt_all_button.setText("Make all")
            self.decrypt_selected_button.setToolTip(
                "Decrypt encrypted images or copy ordinary RPG Maker PNGs into the "
                "editable workspace."
            )
            self.decrypt_all_button.setToolTip(
                "Make every encrypted or ordinary RPG Maker PNG editable without "
                "overwriting existing work."
            )
        else:
            self.decrypt_selected_button.setText("Make selected")
            self.decrypt_all_button.setText("Make all")
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
        set_status_text(self.status_label, "Scanning image folders…", "info")
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
        current_folders = self.folder_combo.selected_folders()
        folders = sorted(
            {asset.relative_png.parent.as_posix() for asset in assets}, key=str.casefold
        )
        self.folder_combo.set_folders(folders, current_folders)
        self.folder_combo.blockSignals(False)
        encrypted = sum(asset.has_encrypted for asset in assets)
        editable = sum(asset.has_plain for asset in assets)
        set_status_text(self.status_label,
            f"{profile_label(self.engine_id)} · found {len(assets):,} images · "
            f"{encrypted:,} encrypted · "
            f"{editable:,} editable PNG copies · {len(self.selected_ids):,} highlighted",
            "success",
        )
        self._update_prepare_scope()
        self._apply_filters()
        self._update_page_scroll_extent()

    def _scan_error(self, generation: int, message: str) -> None:
        if generation != self._scan_generation:
            return
        self._set_actions_enabled(False)
        set_status_text(self.status_label, f"Image scan failed: {message}", "error")
        QMessageBox.critical(self, "Image Scan Failed", message)

    def _apply_filters(self) -> None:
        self.selected_ids.clear()
        query = self.search_edit.text().strip().casefold()
        folders = self.folder_combo.selected_folders()
        state = self.state_combo.currentData()
        filtered: list[ImageAsset] = []
        for asset in self.assets:
            if query and query not in asset.asset_id.casefold():
                continue
            if folders and asset.relative_png.parent.as_posix() not in folders:
                continue
            if state == "editable" and not asset.has_plain:
                continue
            filtered.append(asset)
        self.filtered_assets = filtered
        self.page = 0
        self._render_page()
        self._update_selection_status()

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
            item.setSizeHint(self._thumbnail_item_size)
            item.setData(_ASSET_ID_ROLE, asset.asset_id)
            self._update_asset_item(item, asset)
            self.image_list.addItem(item)
            item.setSelected(asset.asset_id in self.selected_ids)
        self.image_list.blockSignals(False)
        self.page_label.setText(
            f"Page {self.page + 1} of {page_count} · {len(self.filtered_assets):,} images"
        )
        self._page_count = page_count
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

    @staticmethod
    def _update_asset_item(item: QListWidgetItem, asset: ImageAsset) -> None:
        if asset.has_plain:
            if asset.has_encrypted:
                kind = "encrypted + editable"
            elif asset.has_runtime_plain:
                kind = "runtime PNG + editable"
            else:
                kind = "editable PNG"
        elif asset.has_encrypted:
            kind = "encrypted"
        elif asset.has_runtime_plain:
            kind = "runtime PNG"
        else:
            kind = "editable PNG"
        item.setToolTip(f"{asset.asset_id}\n{kind}")

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
        self.selected_ids.clear()
        self.page += delta
        self._render_page()
        self._update_selection_status()

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
        set_status_text(self.status_label,
            f"{len(self.filtered_assets):,} matching images · "
            f"{len(self.selected_ids):,} highlighted · "
            f"{sum(asset.has_plain for asset in self.assets):,} editable"
        )

    def _update_prepare_scope(self) -> None:
        compact = getattr(self, "_action_labels_compact", False)
        if self.selected_ids:
            self.prepare_button.setText("Patch" if compact else "Patch selected")
        else:
            self.prepare_button.setText("Patch all")
        if hasattr(self, "action_host"):
            self._arrange_action_bar()

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
            self._preview_pixmap = pixmap
            self._render_preview_pixmap()
        except Exception as exc:
            self._preview_pixmap = None
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText(f"Preview unavailable\n{exc}")
        details = [asset.asset_id, f"Engine: {profile_label(self.engine_id)}"]
        if asset.has_encrypted:
            details.append(f"Runtime encrypted: {asset.encrypted_path}")
            runtime_state = "Encrypted source"
        elif asset.has_runtime_plain:
            details.append(f"Runtime PNG: {asset.runtime_plain_path}")
            runtime_state = "PNG source"
        else:
            runtime_state = "Editable only"
        details.append(
            f"Editable PNG: {asset.plain_path}"
            if asset.has_plain
            else f"Editable folder target: {asset.plain_path} (not created)"
        )
        editable_state = (
            "Editable copy ready" if asset.has_plain else "No editable copy"
        )
        detail_text = "\n".join(details)
        self.path_label.setText(
            f"{asset.asset_id}\n"
            f"{runtime_state} · {editable_state}"
        )
        self.path_label.setToolTip(detail_text)
        self.path_label.show()

    def _render_preview_pixmap(self) -> None:
        pixmap = getattr(self, "_preview_pixmap", None)
        if pixmap is None or pixmap.isNull():
            return
        target = self.preview_label.contentsRect().size()
        if target.width() <= 0 or target.height() <= 0:
            return
        self.preview_label.setPixmap(
            pixmap.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def _update_page_scroll_extent(self) -> None:
        """Let the page scroll instead of compressing text and preview rows."""
        if not hasattr(self, "page_content"):
            return
        self.page_content.setMinimumHeight(0)
        self.page_layout.activate()
        self.page_content.setMinimumHeight(self.page_layout.sizeHint().height())

    def _arrange_action_bar(self) -> None:
        """Keep all image actions on one compact, clearly grouped row."""
        if not all(
            hasattr(self, name)
            for name in ("workspace_card", "action_layout", "action_buttons")
        ):
            return
        self._action_layout_mode = "single"

        full_labels = (
            "Open folder",
            "Copy skill",
            "Edit text…",
            "Make selected",
            "Make all",
            "Remove copies",
        )
        compact_labels = ("Open", "Copy", "Text", "Make", "Make all", "Remove")
        for button in self.action_buttons:
            button.setMinimumWidth(0)
            button.setMaximumWidth(16777215)
        for button, label in zip(self.action_buttons[:-1], full_labels):
            button.setText(label)
        self._action_labels_compact = False
        self.prepare_button.setText(
            "Patch selected" if self.selected_ids else "Patch all"
        )

        button_count = len(self.action_buttons)
        page_margins = self.page_layout.contentsMargins()
        card_margins = self.workspace_card.content_layout.contentsMargins()
        viewport_available = (
            self.page_scroll.viewport().contentsRect().width()
            - page_margins.left()
            - page_margins.right()
            - card_margins.left()
            - card_margins.right()
        )
        available = max(
            0,
            min(self.action_host.contentsRect().width(), viewport_available)
            - self.action_layout.horizontalSpacing() * (button_count - 1),
        )
        widest = max(action_button_width_hint(button) for button in self.action_buttons)
        if widest * button_count > available:
            for button, label in zip(self.action_buttons[:-1], compact_labels):
                button.setText(label)
            self._action_labels_compact = True
            self.prepare_button.setText("Patch all" if not self.selected_ids else "Patch")
            widest = max(
                action_button_width_hint(button) for button in self.action_buttons
            )
        per_button = max(Geometry.CONTROL_COMPACT, available // button_count)
        equalize_button_widths(
            self.action_buttons,
            minimum=0,
            maximum=per_button,
        )

        for button in (self.previous_button, self.next_button):
            button.setMinimumWidth(0)
            button.setMaximumWidth(16777215)
        equalize_button_widths(
            (self.previous_button, self.next_button), minimum=0
        )
        full_page_text = (
            f"Page {self.page + 1} of {getattr(self, '_page_count', 1)} · "
            f"{len(self.filtered_assets):,} images"
        )
        self.page_label.setText(full_page_text)
        pagination_width = (
            self.previous_button.width()
            + self.next_button.width()
            + self.page_label.sizeHint().width()
            + Spacing.SM * 2
        )
        if pagination_width > self.browser_host.contentsRect().width():
            self.page_label.setText(
                f"{self.page + 1}/{getattr(self, '_page_count', 1)} · "
                f"{len(self.filtered_assets):,}"
            )

        grid = self.action_layout
        for button in self.action_buttons:
            grid.removeWidget(button)
        for column in range(7):
            grid.setColumnStretch(column, 0)
        left = Qt.AlignLeft | Qt.AlignVCenter
        for column, button in enumerate(self.action_buttons):
            grid.addWidget(button, 0, column, 1, 1, left)
        grid.setColumnStretch(6, 1)
        self.action_host.updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "preview_label"):
            self._render_preview_pixmap()
        self._arrange_action_bar()

    def eventFilter(self, watched, event) -> bool:
        if (
            hasattr(self, "page_scroll")
            and watched is self.page_scroll.viewport()
            and event.type() == QEvent.Resize
        ):
            # The viewport may change without ImageManager receiving a resize
            # (notably after font scaling changes the page's size hint).
            QTimer.singleShot(0, self._refresh_responsive_layout)
        return super().eventFilter(watched, event)

    def _refresh_responsive_layout(self) -> None:
        self._arrange_action_bar()
        self._update_page_scroll_extent()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._arrange_action_bar()
        self._update_page_scroll_extent()
        QTimer.singleShot(0, self._arrange_action_bar)

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
                filtered_folders = self.folder_combo.selected_folders()
                if self.engine_id == PROFILE_GENERIC:
                    source_root = normalize_generic_image_root(
                        root, self.generic_image_root
                    )
                    source_relative = source_root.relative_to(root)
                    folder = (
                        next(iter(filtered_folders))
                        if len(filtered_folders) == 1
                        else source_relative.as_posix()
                    )
                    relative_folder = Path(folder)
                    if relative_folder.is_absolute() or ".." in relative_folder.parts:
                        raise ValueError(f"Invalid editable image folder: {folder}")
                    target = workspace / relative_folder
                else:
                    content_relative = resolve_content_root(root).relative_to(root)
                    folder = (
                        next(iter(filtered_folders))
                        if len(filtered_folders) == 1
                        else "img"
                    )
                    relative_folder = Path(folder)
                    if relative_folder.is_absolute() or ".." in relative_folder.parts:
                        raise ValueError(f"Invalid editable image folder: {folder}")
                    target = workspace / content_relative / relative_folder
            target.resolve().relative_to(workspace.resolve())
            target.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
                raise RuntimeError("The system file manager could not open the folder.")
            set_status_text(self.status_label, f"Editable images: {target}", "success")
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
            glossary_path = prepare_game_translation_context(game_root)
            replacements = {
                "{{ENGINE_NAME}}": profile.label,
                "{{ENGINE_CONTEXT}}": profile.translation_skill_context,
                "{{GAME_ROOT}}": str(game_root),
                "{{EDITABLE_IMAGES_FOLDER}}": str(self._editable_image_root().resolve()),
                "{{VOCAB_FILE}}": str(glossary_path),
                "{{IMAGE_TOOL_PYTHON}}": str(Path(sys.executable).resolve()),
                "{{IMAGE_INPAINT_CLI}}": str(
                    (PROJECT_ROOT / "scripts" / "image_inpaint.py").resolve()
                ),
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
            set_status_text(self.status_label,
                f"Copied image translation skill for {len(editable_assets):,} editable PNG(s): "
                f"{self._editable_image_root()}",
                "success",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Copy Image Translation Skill", str(exc))

    # ------------------------------------------------ semi-manual image text
    # The other way to translate the pictures on this page. "Copy skill" hands
    # the bitmaps to a coding agent and gets bitmaps back; this reads the text
    # out with OCR, translates it through the tool's own engine, and redraws
    # it. Everything below it lives in gui/image_text_editor.py and
    # util/imagetools/, imported only when asked for - that subsystem needs
    # numpy and OpenCV, which are not installed until somebody wants them.

    def _text_editor_targets(self) -> tuple[Path, list[str]]:
        """``(workspace, relpaths)`` for the images the editor should open.

        Highlighting rows narrows it to those; with nothing highlighted the
        whole editable set is offered, which is the usual case.
        """
        if self.game_root is None:
            raise ValueError("Select a game folder first.")
        game_root = Path(self.game_root).expanduser().resolve()
        workspace = editable_workspace_root(game_root)
        chosen = [
            asset for asset in self._selected_assets() if asset.has_plain
        ] or self._editable_assets()

        relpaths = []
        for asset in chosen:
            try:
                relpaths.append(
                    str(Path(asset.plain_path).resolve().relative_to(workspace))
                )
            except ValueError:
                # An editable copy outside the workspace cannot be addressed
                # relative to it; skipping beats writing a job file whose paths
                # do not resolve.
                continue
        if not relpaths:
            raise ValueError(
                f"None of the editable images sit under {workspace} - nothing to edit."
            )
        return workspace, relpaths

    def build_text_editor(self):
        """Construct the review editor without showing it.

        Separate from ``_open_text_editor`` so the wiring can be tested: the
        dialog is modal, and a test that clicked the button would block on
        ``exec_()`` forever.
        """
        from gui.image_text_editor import ImageTextEditor

        workspace, relpaths = self._text_editor_targets()
        game_root = Path(self.game_root).expanduser().resolve()
        return ImageTextEditor(game_root, workspace, relpaths, self)

    def _open_text_editor(self) -> None:
        if not self._editable_assets():
            QMessageBox.information(
                self,
                "No Editable Images",
                "Make one or more images editable before editing their text.",
            )
            return
        # Imports PyQt and the standard library only, so this is safe to reach
        # before anything the workflow needs has been downloaded.
        from gui.imagetext_resources import ensure_resources

        if not ensure_resources(self):
            return
        try:
            dialog = self.build_text_editor()
        except Exception as exc:
            QMessageBox.warning(self, "Edit Image Text", str(exc))
            return
        count = len(dialog.job.images)
        dialog.exec_()
        set_status_text(
            self.status_label,
            f"Image text editor closed - {count:,} image(s) in the job.",
            "info",
        )

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
        worker.status.connect(
            lambda message: set_status_text(self.status_label, message, "info")
        )
        worker.done.connect(
            lambda finished_action, result, affected=tuple(assets): self._action_done(
                finished_action, result, affected
            )
        )
        worker.error.connect(self._action_error)
        self._action_worker = worker
        worker.start()

    def _action_done(
        self,
        action: str,
        result,
        affected_assets: tuple[ImageAsset, ...] = (),
    ) -> None:
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
        if action in {"decrypt", "make_editable"}:
            self._refresh_after_make_editable(affected_assets)
        set_status_text(
            self.status_label,
            summary,
            "warning" if result.errors else "success",
        )
        if action not in {"decrypt", "make_editable"}:
            self._start_scan()

    def _refresh_after_make_editable(
        self, affected_assets: tuple[ImageAsset, ...]
    ) -> None:
        """Expose newly editable state without rescanning the project."""

        if self.state_combo.currentData() == "editable":
            # This filter's membership changed, so rebuild only the visible
            # page instead of rescanning every project image folder.
            self._apply_filters()
        else:
            affected_ids = {asset.asset_id for asset in affected_assets}
            current = self.image_list.currentItem()
            current_id = (
                current.data(_ASSET_ID_ROLE) if current is not None else None
            )
            for index in range(self.image_list.count()):
                item = self.image_list.item(index)
                asset_id = item.data(_ASSET_ID_ROLE)
                if asset_id not in affected_ids:
                    continue
                asset = self.assets_by_id.get(asset_id)
                if asset is None:
                    continue
                self._update_asset_item(item, asset)
                item.setSelected(asset_id in self.selected_ids)
            if current_id in affected_ids and current is not None:
                self._show_preview(current)

        self._set_actions_enabled(True)
        self._update_prepare_scope()

    def _action_error(self, message: str) -> None:
        set_status_text(self.status_label, f"Image action failed: {message}", "error")
        self._set_actions_enabled(True)
        QMessageBox.critical(self, "Image Action Failed", message)

    def _set_actions_enabled(self, enabled: bool) -> None:
        for button in (
            self.open_workspace_button,
            self.copy_translation_button,
            self.edit_text_button,
            self.decrypt_selected_button,
            self.decrypt_all_button,
            self.remove_button,
            self.prepare_button,
        ):
            button.setEnabled(enabled)
        has_editable = bool(self._editable_assets())
        self.copy_translation_button.setEnabled(enabled and has_editable)
        self.edit_text_button.setEnabled(enabled and has_editable)

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
            set_status_text(
                self.status_label, "Finishing image scan/preview before closing…", "info"
            )
            event.ignore()
            return
        super().closeEvent(event)
