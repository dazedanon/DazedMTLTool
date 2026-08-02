#!/usr/bin/env python3
"""Capture sanitized application pages and report contract geometry.

The harness runs in a temporary working directory with isolated settings. It
disables update/model network checks and never clicks production actions.
Use the dedicated workflow harness for the full per-step state matrix.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image, ImageDraw, ImageFont
from PyQt5.QtCore import QCoreApplication, QPoint, QSettings
from PyQt5.QtGui import QFont, QFontMetrics
from PyQt5.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QPushButton,
    QToolButton,
    QTreeWidgetItem,
    QWidget,
)

from gui.theme import COLORS, apply_application_theme, scaled_stylesheet
from gui.ui_components import normalize_default_layout_tokens


def _parse_sizes(raw: str) -> list[tuple[int, int]]:
    result = []
    for item in raw.split(","):
        width, height = item.strip().lower().split("x", 1)
        result.append((int(width), int(height)))
    return result


def _parse_scales(raw: str) -> list[float]:
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


def _apply_font_scale(app: QApplication, scale: float) -> None:
    apply_application_theme(app, font_scale=scale)
    font = QFont(app.font())
    font.setPointSize(max(6, round(9 * scale)))
    app.setFont(font)
    control_height = max(32, QFontMetrics(font).height() + 14)
    for widget in app.allWidgets():
        if (
            widget.inherits("QLineEdit")
            or widget.inherits("QComboBox")
            or widget.inherits("QAbstractSpinBox")
        ):
            widget.setMinimumHeight(control_height)
        original = widget.property("_app_capture_original_stylesheet")
        if original is None:
            original = widget.styleSheet()
            if original:
                widget.setProperty("_app_capture_original_stylesheet", original)
        if original:
            widget.setStyleSheet(scaled_stylesheet(str(original), scale))
    normalize_default_layout_tokens(app.allWidgets())


def _widget_record(widget: QWidget, host: QWidget, index: int) -> dict:
    top_left = widget.mapTo(host, widget.rect().topLeft())
    rect = widget.rect()
    text = ""
    if hasattr(widget, "text") and callable(widget.text):
        try:
            text = widget.text()[:160]
        except TypeError:
            pass
    plain_text = re.sub(r"<[^>]+>", "", text)
    text_width = widget.fontMetrics().horizontalAdvance(plain_text)
    if hasattr(widget, "icon") and callable(widget.icon):
        try:
            if not widget.icon().isNull():
                text_width += widget.iconSize().width() + 8
        except TypeError:
            pass
    layout = widget.layout() if not isinstance(widget, QMainWindow) else None
    parent = widget.parentWidget()
    parent_contents = None
    if parent is not None:
        contents = parent.contentsRect()
        # Map through the already-validated child. Some Qt-owned dialog
        # internals expose a parent wrapper that can disappear between
        # findChildren() and parent.mapTo(), which can segfault PyQt rather
        # than raise a Python exception.
        parent_top_left = widget.mapTo(
            host,
            QPoint(
                contents.x() - widget.x(),
                contents.y() - widget.y(),
            ),
        )
        parent_contents = [
            parent_top_left.x(),
            parent_top_left.y(),
            contents.width(),
            contents.height(),
        ]
    record = {
        "index": index,
        "class": widget.metaObject().className(),
        "object_name": widget.objectName(),
        "text": text,
        "geometry": [top_left.x(), top_left.y(), rect.width(), rect.height()],
        "minimum": [widget.minimumWidth(), widget.minimumHeight()],
        "maximum": [widget.maximumWidth(), widget.maximumHeight()],
        "size_hint": [widget.sizeHint().width(), widget.sizeHint().height()],
        "text_width": text_width,
        "enabled": widget.isEnabled(),
        "word_wrap": bool(widget.wordWrap()) if isinstance(widget, QLabel) else False,
        "parent_contents": parent_contents,
        "parent_class": parent.metaObject().className() if parent is not None else "",
        "equal_width_group": str(widget.property("appEqualWidthGroup") or ""),
        "required_parent_inset": int(
            widget.property("appRequiredParentInset") or 0
        ),
    }
    if layout is not None:
        margins = layout.contentsMargins()
        record["layout"] = {
            "margins": [margins.left(), margins.top(), margins.right(), margins.bottom()],
            "spacing": layout.spacing(),
            "count": layout.count(),
        }
    return record


def _geometry_report(
    host: QWidget,
    slug: str,
    size: tuple[int, int],
    scale: float,
    state: str,
) -> dict:
    widgets = [host, *host.findChildren(QWidget)]
    visible = [
        widget
        for widget in widgets
        if widget.isVisible() and not widget.objectName().startswith("qt_")
    ]
    records = [_widget_record(widget, host, index) for index, widget in enumerate(visible)]
    allowed_spacing = {-1, 0, 4, 8, 12, 16, 24, 32}
    violations = []
    equal_width_groups = {}
    for record in records:
        layout = record.get("layout")
        if record["class"] == "QStackedWidget":
            layout = None
        if layout and layout["spacing"] not in allowed_spacing:
            violations.append({
                "kind": "off-token-spacing",
                "widget": record["object_name"] or record["class"],
                "value": layout["spacing"],
            })
        if layout:
            for value in layout["margins"]:
                if value not in allowed_spacing:
                    violations.append({
                        "kind": "off-token-margin",
                        "widget": record["object_name"] or record["class"],
                        "value": value,
                    })
        x, y, width, height = record["geometry"]
        interactive = record["class"].endswith("Button") or record["class"] in {
            "QLineEdit", "QComboBox", "QSpinBox", "QDoubleSpinBox"
        }
        if record["object_name"] in {"ScrollLeftButton", "ScrollRightButton"}:
            interactive = False
        if interactive and (width < 32 or height < 32):
            violations.append({
                "kind": "small-interactive-target",
                "widget": record["object_name"] or record["text"] or record["class"],
                "geometry": [x, y, width, height],
            })
        parent_contents = record.get("parent_contents")
        qt_internal_control = record.get("parent_class") in {
            "QComboBox", "ConfigComboBox", "QAbstractSpinBox",
            "QSpinBox", "QDoubleSpinBox",
        }
        if interactive and parent_contents and not qt_internal_control:
            parent_x, parent_y, parent_width, parent_height = parent_contents
            tolerance = 1
            if (
                x < parent_x - tolerance
                or y < parent_y - tolerance
                or x + width > parent_x + parent_width + tolerance
                or y + height > parent_y + parent_height + tolerance
            ):
                violations.append({
                    "kind": "outside-parent-bounds",
                    "widget": record["object_name"] or record["text"] or record["class"],
                    "geometry": [x, y, width, height],
                    "parent_contents": parent_contents,
                })
            required_inset = record.get("required_parent_inset", 0)
            if required_inset:
                clearances = [
                    x - parent_x,
                    y - parent_y,
                    parent_x + parent_width - (x + width),
                    parent_y + parent_height - (y + height),
                ]
                if min(clearances) < required_inset:
                    violations.append({
                        "kind": "insufficient-parent-edge-inset",
                        "widget": record["object_name"] or record["text"] or record["class"],
                        "geometry": [x, y, width, height],
                        "parent_contents": parent_contents,
                        "required_inset": required_inset,
                        "clearances": clearances,
                    })
        if interactive and (x < -1 or x + width > host.width() + 1):
            violations.append({
                "kind": "outside-host-horizontal-bounds",
                "widget": record["object_name"] or record["text"] or record["class"],
                "geometry": [x, y, width, height],
                "host_width": host.width(),
            })
        group = record.get("equal_width_group")
        if group:
            equal_width_groups.setdefault(group, []).append(record)
        icon_only = len(record["text"].strip()) <= 2
        clipping_limit = width if record["class"] == "QLabel" or icon_only else max(0, width - 8)
        if (
            record["class"] in {"QLabel", "QPushButton", "QToolButton"}
            and record["text"]
            and not record["word_wrap"]
            and record["text_width"] > clipping_limit
        ):
            violations.append({
                "kind": "possible-text-clipping",
                "widget": record["object_name"] or record["text"] or record["class"],
                "width": width,
                "text_width": record["text_width"],
            })

    for group in equal_width_groups.values():
        sizes = {(record["geometry"][2], record["geometry"][3]) for record in group}
        if len(group) > 1 and len(sizes) > 1:
            violations.append({
                "kind": "peer-button-size-mismatch",
                "widgets": [record["text"] or record["object_name"] for record in group],
                "sizes": sorted([list(size) for size in sizes]),
            })

    return {
        "page": slug,
        "viewport": list(size),
        "font_scale": scale,
        "fixture_state": state,
        "widgets": records,
        "violations": violations,
    }


def _save_overlay(source: Path, target: Path, report: dict) -> None:
    image = Image.open(source).convert("RGBA")
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    for x in range(0, width, 8):
        draw.line((x, 0, x, height), fill=(117, 190, 255, 28), width=1)
    for y in range(0, height, 8):
        draw.line((0, y, width, y), fill=(117, 190, 255, 28), width=1)
    for record in report["widgets"]:
        if not record["object_name"]:
            continue
        x, y, w, h = record["geometry"]
        if w <= 0 or h <= 0:
            continue
        draw.rectangle((x, y, x + w - 1, y + h - 1), outline=(242, 201, 76, 110), width=1)
    image.save(target)


def _contact_sheet(paths: list[tuple[str, Path]], target: Path, title: str) -> None:
    if not paths:
        return
    images = [(slug, Image.open(path).convert("RGB")) for slug, path in paths]
    thumb_width = 560
    gap = 16
    label_height = 28
    thumbs = []
    for slug, image in images:
        ratio = thumb_width / image.width
        thumbs.append((slug, image.resize(
            (thumb_width, round(image.height * ratio)), Image.Resampling.LANCZOS
        )))
    row_height = max(image.height for _, image in thumbs) + label_height
    rows = (len(thumbs) + 1) // 2
    sheet = Image.new(
        "RGB",
        (thumb_width * 2 + gap * 3, rows * row_height + gap * (rows + 1) + 32),
        COLORS.canvas,
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    draw.text((gap, 8), title, fill=COLORS.text_primary, font=font)
    for index, (slug, image) in enumerate(thumbs):
        column, row = index % 2, index // 2
        x = gap + column * (thumb_width + gap)
        y = 32 + gap + row * (row_height + gap)
        draw.text((x, y), slug, fill=COLORS.text_secondary, font=font)
        sheet.paste(image, (x, y + label_height))
    sheet.save(target)


def _create_image_fixture(root: Path) -> Path:
    """Create a small deterministic RPG Maker project for image captures."""

    game_root = root / "fixture-game"
    image_root = game_root / "img" / "pictures"
    data_root = game_root / "data"
    image_root.mkdir(parents=True)
    data_root.mkdir(parents=True)
    data_root.joinpath("System.json").write_text(
        '{"encryptionKey":"00112233445566778899aabbccddeeff"}',
        encoding="utf-8",
    )
    colors = (
        "#D97757", "#5B8DEF", "#73C991", "#C586C0",
        "#E5C07B", "#56B6C2", "#BE5046", "#98C379",
    )
    for index, color in enumerate(colors, start=1):
        Image.new("RGBA", (320, 180), color).save(
            image_root / f"Scene_{index:02d}_localized_title.png"
        )
    return game_root


def _settle_fixture_workers(window, app: QApplication) -> None:
    """Finish bounded fixture workers before measuring mutable widget trees."""

    for _attempt in range(8):
        app.processEvents()
        image_manager = window.image_manager_tab
        workers = [
            *image_manager._scan_workers,
            *image_manager._thumbnail_workers,
        ]
        batch_worker = getattr(window.batch_tab, "_worker", None)
        if batch_worker is not None:
            workers.append(batch_worker)
        running = [worker for worker in workers if worker.isRunning()]
        for worker in running:
            worker.wait(5000)
        app.processEvents()
        if not any(worker.isRunning() for worker in workers):
            return
    raise RuntimeError("Fixture background workers did not settle before capture")


def _capture_targets(window) -> list[tuple[str, int, int | None]]:
    targets = [
        ("guide", window.PAGE_GUIDE, None),
        ("workflow-rpgmaker", window.PAGE_WORKFLOW, 0),
        ("workflow-wolf", window.PAGE_WORKFLOW, 1),
        ("images", window.PAGE_IMAGES, None),
        ("version-update", window.PAGE_VERSION_UPDATE, None),
        ("translation", window.PAGE_TRANSLATION, None),
        ("batches", window.PAGE_BATCHES, None),
        ("skills", window.PAGE_SKILLS, None),
        ("configuration-general", window.PAGE_CONFIG, 0),
        ("configuration-rpgmaker", window.PAGE_CONFIG, 1),
        ("configuration-wolf", window.PAGE_CONFIG, 2),
        ("configuration-csv", window.PAGE_CONFIG, 3),
        ("configuration-srpg", window.PAGE_CONFIG, 4),
        ("evaluation", window.PAGE_EVALUATION, None),
    ]
    return targets


def _apply_state(window, state: str) -> None:
    current = window.content_stack.currentWidget()
    translation = getattr(window, "translation_tab", None)
    version_update = getattr(window, "version_update_tab", None)
    image_manager = getattr(window, "image_manager_tab", None)

    # State captures reuse one window. Restore Translation's semantic state as
    # well as generic button/label properties so an active run cannot leak into
    # a later default capture at another size or font scale.
    if translation is not None:
        translation._batch_active = False
        translation._batch_ui_phase = "idle"
        translation.file_stack.setCurrentIndex(0)
        if translation.file_card.title_label is not None:
            translation.file_card.title_label.setText("Files to translate")
        translation._set_activity_visible(False)
        translation.stop_button.setVisible(False)
        translation.totals_widget.setVisible(False)
        translation._on_mode_changed(translation.mode_combo.currentText())
        translation._set_run_controls_enabled(True)
    if current is version_update:
        version_update.review_card.setVisible(False)
        version_update.create_card.setVisible(False)
        version_update.empty_state_spacer.setVisible(True)
        version_update.progress.setVisible(False)
        version_update.progress_label.setVisible(False)
        version_update.cancel_scan_btn.setVisible(False)
        version_update.tree.clear()
        version_update.details.clear()
        version_update.summary_label.setText("Run a preview to build the update plan.")
    buttons = [
        *current.findChildren(QPushButton),
        *current.findChildren(QToolButton),
    ]
    for button in buttons:
        original_enabled = button.property("_capture_enabled")
        if original_enabled is not None:
            button.setEnabled(bool(original_enabled))
            button.setProperty("_capture_enabled", None)
    for label in current.findChildren(QLabel):
        original_text = label.property("_capture_text")
        if original_text is not None:
            label.setText(str(original_text))
            label.setProperty("_capture_text", None)
            label.setObjectName(str(label.property("_capture_object_name") or ""))
            label.setProperty("_capture_object_name", None)
            label.setWordWrap(bool(label.property("_capture_word_wrap")))
            label.setProperty("_capture_word_wrap", None)

    if state == "default":
        return
    if state == "disabled":
        for button in buttons:
            button.setProperty("_capture_enabled", button.isEnabled())
            button.setEnabled(False)
        return
    if state == "error":
        labels = current.findChildren(QLabel)
        if labels:
            label = labels[-1]
            label.setProperty("_capture_text", label.text())
            label.setProperty("_capture_object_name", label.objectName())
            label.setProperty("_capture_word_wrap", label.wordWrap())
            label.setText("Could not load the requested data · no changes were made")
            label.setObjectName("appStatusText")
            label.setWordWrap(True)
            label.setProperty("state", "error")
            label.style().unpolish(label)
            label.style().polish(label)
        return
    if state == "active":
        if current is image_manager:
            if image_manager.image_list.count():
                image_manager.image_list.setCurrentRow(0)
                image_manager.image_list.item(0).setSelected(True)
                image_manager._selection_changed()
            return
        if current is version_update:
            version_update.review_card.setVisible(True)
            version_update.create_card.setVisible(True)
            version_update.empty_state_spacer.setVisible(False)
            version_update.progress.setVisible(True)
            version_update.progress.setRange(0, 100)
            version_update.progress.setValue(100)
            version_update.progress_label.setVisible(True)
            version_update.progress_label.setText("Preview complete")
            version_update.summary_label.setText(
                "382 files analyzed · 6 changes need review · 24 translations preserved"
            )
            item = QTreeWidgetItem(
                ["Merge game data", "data/Map001.json", "RPG Maker JSON", "Review recommended"]
            )
            version_update.tree.addTopLevelItem(item)
            version_update.tree.setCurrentItem(item)
            version_update.details.setPlainText(
                "What will happen\n\nKeep reviewed local dialogue while applying the newer official map structure."
            )
            version_update.apply_btn.setEnabled(True)
            version_update.custom_apply_btn.setEnabled(True)
            return
        if current is not translation:
            return
        names = [
            translation.file_list.item(index).text()
            for index in range(min(5, translation.file_list.count()))
        ]
        translation.file_progress_items.clear()
        translation.progress_table.setRowCount(0)
        for name in names:
            translation.create_progress_item(name)
        if names:
            translation._set_progress_row(
                names[0], status="Translating", progress="42%", tokens="1,240 / 380"
            )
        for name in names[1:]:
            translation._set_progress_row(name, status="Queued", progress="Waiting")
        translation.file_stack.setCurrentIndex(1)
        if translation.file_card.title_label is not None:
            translation.file_card.title_label.setText("Translation progress")
        translation._batch_active = True
        translation._batch_ui_phase = "collect"
        translation._set_progress_view_mode(True, len(names))
        translation.batch_collect_status.setText(
            "Pass 1/2: collecting requests from the selected files…"
        )
        translation.batch_overall_bar.setValue(25)
        translation._set_activity_visible(True)
        translation._set_run_controls_enabled(False)
        translation.translate_button.setText("Run in progress…")
        translation.translate_button.updateGeometry()
        translation.stop_button.setVisible(True)
        translation.totals_widget.setVisible(True)
        translation.totals_tokens_label.setText("Tokens: 1,240 in / 380 out")
        translation.totals_cost_label.setText("Estimated cost: $0.0184")
        translation.translation_log_viewer.clear_log()
        translation.translation_log_viewer.append_log_message(
            "[BATCH] Collecting translation requests from 5 selected files"
        )
        translation.translation_log_viewer.append_log_message(
            "Map001.json: queued 42 dialogue entries"
        )
        return
    raise ValueError(f"Unknown state: {state}")


def capture(
    output: Path,
    sizes: list[tuple[int, int]],
    scales: list[float],
    states: list[str],
    overlay: bool,
) -> None:
    output = output.resolve()
    QCoreApplication.setOrganizationName("DazedTranslationsCapture")
    QCoreApplication.setApplicationName("DazedTLAppVisualCapture")

    with tempfile.TemporaryDirectory(prefix="dazedtl-app-capture-") as temp_dir:
        previous_cwd = Path.cwd()
        os.chdir(temp_dir)
        try:
            app = QApplication.instance() or QApplication([])
            app.setStyle("Fusion")
            apply_application_theme(app)

            from gui.main import DazedMTLGUI, UpdateDialog

            fixture_root = _create_image_fixture(Path(temp_dir))
            fixture_settings = QSettings(
                str(Path(temp_dir) / "settings.ini"), QSettings.IniFormat
            )
            fixture_settings.setValue("workflow/last_game_folder", str(fixture_root))

            with (
                patch.object(DazedMTLGUI, "start_background_update_check", lambda self: None),
                patch("gui.config_tab.ConfigTab.fetch_models", lambda self, silent=False: None),
                patch(
                    "gui.evaluation_tab.EvaluationTab._schedule_candidate_model_scan",
                    lambda self, widgets, **kwargs: None,
                ),
                patch("gui.evaluation_tab.evaluation.latest_run", return_value=None),
                patch("gui.evaluation_tab.evaluation.list_runs", return_value=[]),
                patch("util.translation._load_litellm_pricing", return_value={}),
                patch("util.batch_history.list_local_batches", return_value=[]),
                patch("gui.main.QSettings", return_value=fixture_settings),
                patch(
                    "gui.image_manager.QSettings",
                    return_value=fixture_settings,
                ),
            ):
                window = DazedMTLGUI()
                window._ensure_workflow_container()
                window.setObjectName("appCaptureWindow")
                window.setWindowTitle("DazedTL · Sanitized UI Fixture")
                _settle_fixture_workers(window, app)

                for width, height in sizes:
                    for scale in scales:
                        for state in states:
                            _apply_font_scale(app, scale)
                            run_dir = output / "current" / state / f"{width}x{height}-{scale:g}"
                            run_dir.mkdir(parents=True, exist_ok=True)
                            window.resize(width, height)
                            window.show()
                            app.processEvents()
                            window.config_tab._update_general_label_width()
                            window.image_manager_tab._update_page_scroll_extent()
                            for workflow in (
                                window.workflow_tab,
                                window.wolf_workflow_tab,
                            ):
                                update_shell = getattr(
                                    workflow, "_update_responsive_shell", None
                                )
                                if callable(update_shell):
                                    update_shell()
                                else:
                                    rail = getattr(workflow, "_step_rail", None)
                                    if rail is not None:
                                        rail.set_compact(
                                            workflow.width() < 1320
                                            or rail.labels_require_compact_mode()
                                        )
                            app.processEvents()

                            images = []
                            reports = []
                            for slug, page, subpage in _capture_targets(window):
                                window.switch_page(page)
                                if page == window.PAGE_WORKFLOW and subpage is not None:
                                    window.workflow_engine_combo.setCurrentIndex(subpage)
                                elif page == window.PAGE_CONFIG and subpage is not None:
                                    window.config_tab.switch_page(subpage)
                                elif (
                                    page == window.PAGE_IMAGES
                                    and window.image_manager_tab.image_list.count()
                                ):
                                    window.image_manager_tab.image_list.setCurrentRow(0)
                                app.processEvents()
                                _apply_state(window, state)
                                app.processEvents()

                                image_path = run_dir / f"{slug}.png"
                                window.grab().save(str(image_path), "PNG")
                                report = _geometry_report(
                                    window, slug, (width, height), scale, state
                                )
                                reports.append(report)
                                images.append((slug, image_path))
                                if overlay:
                                    _save_overlay(
                                        image_path, run_dir / f"{slug}-overlay.png", report
                                    )

                            if state == "default":
                                dialog = UpdateDialog(
                                    window,
                                    pending_tool_sha="1234567890abcdef1234567890abcdef12345678",
                                )
                                dialog._show_pending_updates()
                                dialog.show()
                                app.processEvents()
                                dialog_path = run_dir / "update-dialog.png"
                                dialog.grab().save(str(dialog_path), "PNG")
                                dialog_report = _geometry_report(
                                    dialog,
                                    "update-dialog",
                                    (dialog.width(), dialog.height()),
                                    scale,
                                    state,
                                )
                                reports.append(dialog_report)
                                images.append(("update-dialog", dialog_path))
                                if overlay:
                                    _save_overlay(
                                        dialog_path,
                                        run_dir / "update-dialog-overlay.png",
                                        dialog_report,
                                    )
                                dialog.close()

                            (run_dir / "geometry.json").write_text(
                                json.dumps(reports, indent=2, ensure_ascii=False),
                                encoding="utf-8",
                            )
                            _contact_sheet(
                                images,
                                run_dir / "contact-sheet.png",
                                f"DazedTL · {state} · {width}x{height} · font {scale:g}x",
                            )
                window.close()
                app.processEvents()
        finally:
            os.chdir(previous_cwd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=PROJECT_ROOT / ".tmp-ui" / "application"
    )
    parser.add_argument("--sizes", default="1440x900,1280x720")
    parser.add_argument("--font-scales", default="1.0")
    parser.add_argument("--states", default="default")
    parser.add_argument("--overlay", action="store_true")
    args = parser.parse_args()
    capture(
        args.output,
        _parse_sizes(args.sizes),
        _parse_scales(args.font_scales),
        [item.strip() for item in args.states.split(",") if item.strip()],
        args.overlay,
    )
    print(f"Application captures written to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
