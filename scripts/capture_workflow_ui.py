#!/usr/bin/env python3
"""Render deterministic, sanitized RPG Maker workflow reference images.

This is deliberately a presentation-only harness.  It uses an isolated
QSettings file, never triggers folder detection or workflow actions, and blocks
page-change signals so leaving Project cannot auto-import anything.
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

from PIL import Image, ImageChops, ImageDraw, ImageFont
from PyQt5.QtCore import QCoreApplication, QSettings, Qt
from PyQt5.QtGui import QFont, QFontMetrics
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.theme import COLORS, apply_application_theme, scaled_stylesheet


STEP_SLUGS = (
    "project",
    "prepare",
    "setup",
    "phase-1",
    "phase-2",
    "export",
    "rewrap",
    "qa",
    "images",
    "playtest",
)


def _parse_sizes(raw: str) -> list[tuple[int, int]]:
    sizes: list[tuple[int, int]] = []
    for item in raw.split(","):
        width, height = item.lower().strip().split("x", 1)
        sizes.append((int(width), int(height)))
    return sizes


def _parse_scales(raw: str) -> list[float]:
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


def _apply_font_scale(app: QApplication, scale: float) -> None:
    apply_application_theme(app, font_scale=scale)
    font = QFont(app.font())
    font.setPointSize(max(6, round(9 * scale)))
    app.setFont(font)
    control_height = max(30, QFontMetrics(font).height() + 14)
    for widget in app.allWidgets():
        if widget.inherits("QLineEdit") or widget.inherits("QComboBox") or widget.inherits("QAbstractSpinBox"):
            widget.setMinimumHeight(control_height)
        original = widget.property("_capture_original_stylesheet")
        if original is None:
            original = widget.styleSheet()
            if original:
                widget.setProperty("_capture_original_stylesheet", original)
        if original:
            widget.setStyleSheet(scaled_stylesheet(str(original), scale))


def _build_host(settings: QSettings):
    """Build the real workflow widget beneath a deterministic engine bar."""

    from gui.workflow_tab import WorkflowTab

    with patch("gui.workflow_tab.QSettings", return_value=settings):
        workflow = WorkflowTab()
    workflow._detected_on_show = True
    workflow.setObjectName("rpgMakerWorkflow")

    host = QWidget()
    host.setObjectName("workflowCaptureHost")
    root = QVBoxLayout(host)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    engine_bar = QWidget()
    engine_bar.setObjectName("workflowEngineBar")
    bar_layout = QHBoxLayout(engine_bar)
    bar_layout.setContentsMargins(16, 8, 16, 8)
    bar_layout.setSpacing(8)
    engine_label = QLabel("Engine:")
    engine_label.setObjectName("workflowEngineLabel")
    bar_layout.addWidget(engine_label)
    combo = QComboBox()
    combo.setObjectName("workflowEngineSelector")
    combo.addItem("RPG Maker (MV/MZ/Ace)")
    combo.addItem("Wolf RPG (WolfDawn)")
    combo.setMinimumWidth(220)
    bar_layout.addWidget(combo)
    bar_layout.addStretch()
    root.addWidget(engine_bar)
    root.addWidget(workflow, 1)
    return host, workflow


def _seed_ready_fixture(workflow) -> None:
    """Populate controls with invented, non-sensitive fixture content."""

    sample_root = "/fixtures/SampleGame"
    sample_data = f"{sample_root}/data"
    workflow.folder_edit.setText(sample_root)
    workflow._data_path = sample_data
    workflow._engine = "MZ"
    workflow.detected_label.setText(
        f"Detected RPG Maker MZ · Data folder: {sample_data}"
    )
    items = [
        {"name": "Actors.json", "category": "core", "size_kb": 18.4, "default": True, "path": f"{sample_data}/Actors.json"},
        {"name": "Items.json", "category": "core", "size_kb": 42.1, "default": True, "path": f"{sample_data}/Items.json"},
        {"name": "CommonEvents.json", "category": "other", "size_kb": 96.8, "default": True, "path": f"{sample_data}/CommonEvents.json"},
        {"name": "Map001.json", "category": "map", "size_kb": 126.3, "default": True, "path": f"{sample_data}/Map001.json"},
        {"name": "Map002.json", "category": "map", "size_kb": 88.7, "default": False, "path": f"{sample_data}/Map002.json"},
        {"name": "System.json", "category": "core", "size_kb": 31.2, "default": True, "path": f"{sample_data}/System.json"},
    ]
    workflow._on_scan_done(items)

    workflow.pp_data_path_label.setText(sample_data)
    workflow.pp_plugins_edit.setText(f"{sample_root}/js/plugins.js")
    workflow.pp_gameupdate_edit.setText(f"{PROJECT_ROOT}/gameupdate")
    workflow.pp_gameupdate_dst_label.setText(sample_root)

    editors = workflow.setup_editors
    editors.vocab_editor.setPlainText(
        "# Game Characters\n"
        "勇者 (Hero) - optimistic protagonist\n"
        "王都 (Royal Capital) - central city\n\n"
        "# Interface\n"
        "道具 (Items) - inventory menu label"
    )
    editors.quirks_editor.setPlainText(
        "# Translation quirks\n- Keep control codes unchanged.\n"
        "- Use concise labels in narrow menu windows."
    )
    editors.game_skill_editor.setPlainText(
        "# Translation frame\nTone: adventurous and warm.\n"
        "Audience: general RPG players."
    )

    workflow._p0_status_lbl.setText("Ready")
    workflow._p1_status_lbl.setText("Waiting for Phase 0")
    workflow._p1b_status_lbl.setText("Not started")
    workflow._step5_mode_hint.setText("Translation mode: Normal Translate")
    workflow._tl_mode_combo.setCurrentIndex(0)

    workflow._p2_loading_config = True
    try:
        for index, checkbox in enumerate(workflow._p2_code_checks.values()):
            checkbox.setChecked(index in (0, 1))
        for index, checkbox in enumerate(workflow._p2_plugin_checks.values()):
            checkbox.setChecked(index in (1, 4))
        for index, checkbox in enumerate(workflow._p2_pattern_checks.values()):
            checkbox.setChecked(index == 0)
    finally:
        workflow._p2_loading_config = False
    workflow._p2_status_lbl.setText("2 code families selected · review required")

    workflow.rewrap_scope_title.setText(f"Game data file scope — {sample_data}")
    workflow.rewrap_file_list.clear()
    for name in ("Actors.json", "Items.json", "CommonEvents.json", "Map001.json", "Map002.json"):
        item = QListWidgetItem(name)
        item.setCheckState(Qt.Checked if name != "Map002.json" else Qt.Unchecked)
        workflow.rewrap_file_list.addItem(item)
    workflow.rewrap_status_label.setText("4 of 5 files selected · scan before applying")
    if hasattr(workflow, "_step6_export_destination"):
        workflow._step6_export_destination.setText(f"Destination: {sample_data}")

    workflow._image_workflow_status.setText(
        "<b>Ready</b><br>Runtime images: 24 · Editable: 6 · "
        "Encryption key: valid · Glossary: available"
    )
    workflow._tli_status_label.setText("Status: not installed")
    workflow._forge_status_label.setText("Status: installed · current")
    workflow._tli_detect_label.setText("Detected editor: Visual Studio Code")

    workflow.log_area.setPlainText(
        "Workflow ready.\n"
        "Detected RPG Maker MZ sample fixture.\n"
        "Found 6 importable files.\n"
        "No actions run in capture mode."
    )


def _apply_fixture_state(workflow, state: str) -> None:
    """Apply one deterministic presentation state after the ready fixture."""

    if state == "ready":
        return
    if state == "empty":
        workflow.folder_edit.clear()
        workflow._data_path = None
        workflow._file_items = []
        workflow.file_list.clear()
        workflow.detected_label.setText("No project detected yet")
        workflow._set_import_buttons_enabled(False)
        workflow.log_area.setPlainText("Choose a game folder to begin.")
        return
    if state == "busy":
        workflow._run_p1_btn.setEnabled(False)
        workflow._p1_status_lbl.setText("Translating 18 of 42 files…")
        workflow.log_area.setPlainText(
            "Translation started.\nProcessing Map014.json…\n18 of 42 files complete."
        )
        workflow._activity_panel.set_summary("Translating 18 of 42 files…", "info")
        workflow._set_activity_visible(True, persist=False)
        return
    if state == "warning":
        workflow._p2_status_lbl.setText("Review required · risky code families selected")
        workflow._phase2_advanced.toggle.setChecked(True)
        workflow._image_workflow_status.setText(
            "<b>Review required</b><br>Encryption key is missing from System.json."
        )
        workflow.log_area.setPlainText(
            "Warning: verify plugin handlers before Phase 2.\n"
            "No game files were changed."
        )
        return
    if state == "error":
        workflow.detected_label.setText(
            "Could not read the selected project · check folder permissions"
        )
        workflow._p1_status_lbl.setText("Failed · open Activity for details")
        workflow.log_area.setPlainText(
            "Error: SampleGame/data could not be read.\n"
            "No files were imported."
        )
        workflow._activity_panel.set_summary("Project scan failed", "error")
        workflow._set_activity_visible(True, persist=False)
        return
    if state == "complete":
        workflow._step_done.update(range(9))
        workflow._refresh_step_strip(9)
        workflow._p0_status_lbl.setText("Complete")
        workflow._p1_status_lbl.setText("Complete")
        workflow._p1b_status_lbl.setText("Complete")
        workflow._p2_status_lbl.setText("Complete · 12 files translated")
        workflow.log_area.setPlainText(
            "Translation complete.\nExported 12 files.\nFinal QA passed."
        )
        workflow._activity_panel.set_summary("Final QA passed", "success")
        return
    if state == "disabled":
        for button in workflow.findChildren(QPushButton):
            if button.objectName() not in {"workflowHelpButton"}:
                button.setEnabled(False)
        workflow.detected_label.setText("Complete Project detection to enable actions")
        workflow.log_area.setPlainText("Actions are waiting for project prerequisites.")
        return
    raise ValueError(f"Unknown fixture state: {state}")


def _widget_record(widget: QWidget, host: QWidget, index: int) -> dict:
    top_left = widget.mapTo(host, widget.rect().topLeft())
    rect = widget.rect()
    font = widget.font()
    record = {
        "index": index,
        "class": widget.metaObject().className(),
        "object_name": widget.objectName(),
        "parent": (
            widget.parentWidget().objectName()
            or widget.parentWidget().metaObject().className()
            if widget.parentWidget() is not None else ""
        ),
        "text": "",
        "geometry": [top_left.x(), top_left.y(), rect.width(), rect.height()],
        "minimum": [widget.minimumWidth(), widget.minimumHeight()],
        "maximum": [widget.maximumWidth(), widget.maximumHeight()],
        "size_hint": [widget.sizeHint().width(), widget.sizeHint().height()],
        "font": {
            "family": font.family(),
            "point_size": font.pointSizeF(),
            "pixel_size": font.pixelSize(),
            "weight": font.weight(),
        },
        "enabled": widget.isEnabled(),
        "visible": widget.isVisibleTo(host),
        "focus": widget.hasFocus(),
        "word_wrap": bool(widget.wordWrap()) if isinstance(widget, QLabel) else False,
    }
    if hasattr(widget, "text") and callable(widget.text):
        try:
            record["text"] = widget.text()[:160]
        except TypeError:
            pass
    plain_text = re.sub(r"<[^>]+>", "", record["text"])
    text_width = widget.fontMetrics().horizontalAdvance(plain_text)
    if hasattr(widget, "icon") and callable(widget.icon):
        try:
            if not widget.icon().isNull():
                text_width += widget.iconSize().width() + 8
        except TypeError:
            pass
    record["text_width"] = text_width
    layout = None if isinstance(widget, QMainWindow) else widget.layout()
    if layout is not None:
        margins = layout.contentsMargins()
        record["layout"] = {
            "class": layout.metaObject().className(),
            "margins": [margins.left(), margins.top(), margins.right(), margins.bottom()],
            "spacing": layout.spacing(),
            "count": layout.count(),
        }
    return record


def _geometry_report(host: QWidget, step: int, size: tuple[int, int], scale: float) -> dict:
    widgets = [host, *host.findChildren(QWidget)]
    visible_widgets = [
        widget for widget in widgets
        if widget.isVisible() and not widget.objectName().startswith("qt_")
    ]
    records = [
        _widget_record(widget, host, index)
        for index, widget in enumerate(visible_widgets)
    ]
    allowed_spacing = {-1, 0, 4, 8, 12, 16, 24, 32}
    violations: list[dict] = []
    for record in records:
        layout = record.get("layout")
        if layout and layout["spacing"] not in allowed_spacing:
            violations.append(
                {
                    "kind": "off-token-spacing",
                    "widget": record["object_name"] or record["class"],
                    "value": layout["spacing"],
                }
            )
        if layout:
            for value in layout["margins"]:
                if value not in allowed_spacing:
                    violations.append(
                        {
                            "kind": "off-token-margin",
                            "widget": record["object_name"] or record["class"],
                            "value": value,
                        }
                    )
        x, y, width, height = record["geometry"]
        if (record["class"].endswith("Button") or record["class"] in {"QLineEdit", "QComboBox"}) and (width < 32 or height < 32):
            violations.append(
                {
                    "kind": "small-interactive-target",
                    "widget": record["object_name"] or record["text"] or record["class"],
                    "geometry": [x, y, width, height],
                }
            )
        icon_only = len(record["text"].strip()) <= 2
        clipping_limit = (
            width if record["class"] == "QLabel" or icon_only
            else max(0, width - 8)
        )
        if (
            record["class"] in {"QLabel", "QPushButton", "QToolButton"}
            and record["text"]
            and not record["word_wrap"]
            and record["text_width"] > clipping_limit
        ):
            violations.append(
                {
                    "kind": "possible-text-clipping",
                    "widget": record["object_name"] or record["text"] or record["class"],
                    "width": width,
                    "text_width": record["text_width"],
                }
            )

    by_parent: dict[QWidget, list[QWidget]] = {}
    for widget in visible_widgets:
        parent = widget.parentWidget()
        if parent is not None:
            by_parent.setdefault(parent, []).append(widget)
    for siblings in by_parent.values():
        for left_index, left in enumerate(siblings):
            for right in siblings[left_index + 1:]:
                intersection = left.geometry().intersected(right.geometry())
                if intersection.width() <= 0 or intersection.height() <= 0:
                    continue
                # Scroll-area internals and stacked-page implementation
                # widgets can intentionally share their parent's rectangle.
                classes = {left.metaObject().className(), right.metaObject().className()}
                if "QWidget" in classes and (
                    left.parentWidget().inherits("QAbstractScrollArea")
                    or left.parentWidget().inherits("QStackedWidget")
                ):
                    continue
                violations.append(
                    {
                        "kind": "sibling-overlap",
                        "left": left.objectName() or left.metaObject().className(),
                        "right": right.objectName() or right.metaObject().className(),
                        "intersection": [
                            intersection.x(), intersection.y(),
                            intersection.width(), intersection.height(),
                        ],
                    }
                )
    return {
        "step": step,
        "slug": STEP_SLUGS[step],
        "viewport": list(size),
        "font_scale": scale,
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
        draw.rectangle((x, y, x + w - 1, y + h - 1), outline=(242, 201, 76, 110), width=1)
    image.save(target)


def _contact_sheet(paths: list[Path], target: Path, title: str) -> None:
    images = [Image.open(path).convert("RGB") for path in paths]
    if not images:
        return
    thumb_width = 560
    label_height = 34
    gap = 16
    thumbs: list[Image.Image] = []
    for image in images:
        ratio = thumb_width / image.width
        thumbs.append(image.resize((thumb_width, round(image.height * ratio)), Image.Resampling.LANCZOS))
    rows = (len(thumbs) + 1) // 2
    row_height = max(image.height for image in thumbs) + label_height
    sheet = Image.new(
        "RGB",
        (thumb_width * 2 + gap * 3, rows * row_height + gap * (rows + 1) + 32),
        COLORS.canvas,
    )
    draw = ImageDraw.Draw(sheet)
    draw.text((gap, 8), title, fill=COLORS.text_primary, font=ImageFont.load_default())
    for index, image in enumerate(thumbs):
        column = index % 2
        row = index // 2
        x = gap + column * (thumb_width + gap)
        y = 32 + gap + row * (row_height + gap)
        draw.text((x, y), f"Step {index}: {STEP_SLUGS[index]}", fill=COLORS.text_secondary, font=ImageFont.load_default())
        sheet.paste(image, (x, y + label_height))
    sheet.save(target)


def capture(
    output: Path,
    sizes: list[tuple[int, int]],
    scales: list[float],
    overlay: bool,
    states: list[str] | None = None,
) -> None:
    QCoreApplication.setOrganizationName("DazedTranslationsCapture")
    QCoreApplication.setApplicationName("DazedTLVisualCapture")
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    apply_application_theme(app)

    states = states or ["ready"]
    with tempfile.TemporaryDirectory(prefix="dazedtl-ui-capture-") as temp_dir:
        for state in states:
            settings = QSettings(
                str(Path(temp_dir) / f"settings-{state}.ini"), QSettings.IniFormat
            )
            host, workflow = _build_host(settings)
            _seed_ready_fixture(workflow)
            _apply_fixture_state(workflow, state)

            window = QMainWindow()
            window.setObjectName("workflowCaptureWindow")
            window.setCentralWidget(host)
            window.setWindowTitle("DazedTL · RPG Maker Workflow · Visual Fixture")

            for width, height in sizes:
                for scale in scales:
                    _apply_font_scale(app, scale)
                    run_dir = output / "current" / state / f"{width}x{height}-{scale:g}"
                    run_dir.mkdir(parents=True, exist_ok=True)
                    window.resize(width, height)
                    window.show()
                    for _ in range(5):
                        app.processEvents()
                    # Workflow construction schedules safe, deferred refreshes.
                    # Re-apply the sanitized fixture after they have drained so
                    # a real filesystem miss cannot replace the visual state.
                    _seed_ready_fixture(workflow)
                    _apply_fixture_state(workflow, state)
                    app.processEvents()

                    step_paths: list[Path] = []
                    geometry: list[dict] = []
                    workflow._step_tabs.blockSignals(True)
                    try:
                        for step, slug in enumerate(STEP_SLUGS):
                            workflow._step_tabs.setCurrentIndex(step)
                            if hasattr(workflow, "_step_rail"):
                                workflow._step_rail.set_current(step)
                            for _ in range(3):
                                app.processEvents()
                            image_path = run_dir / f"step-{step:02d}-{slug}.png"
                            window.grab().save(str(image_path), "PNG")
                            report = _geometry_report(window, step, (width, height), scale)
                            report["fixture_state"] = state
                            geometry.append(report)
                            step_paths.append(image_path)
                            if overlay:
                                _save_overlay(
                                    image_path,
                                    run_dir / f"step-{step:02d}-{slug}-overlay.png",
                                    report,
                                )
                    finally:
                        workflow._step_tabs.blockSignals(False)

                    (run_dir / "geometry.json").write_text(
                        json.dumps(geometry, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    _contact_sheet(
                        step_paths,
                        run_dir / "contact-sheet.png",
                        f"RPG Maker · {state} · {width}x{height} · font {scale:g}x",
                    )
            window.close()
            workflow.close()
            app.processEvents()


def compare_captures(output: Path, baseline: Path) -> dict:
    """Create deterministic pixel diffs against another capture tree."""

    current_root = output / "current"
    baseline_root = baseline / "current" if (baseline / "current").is_dir() else baseline
    diff_root = output / "diff"
    records: list[dict] = []
    for current in sorted(current_root.rglob("step-*.png")):
        if current.name.endswith("-overlay.png"):
            continue
        relative = current.relative_to(current_root)
        expected = baseline_root / relative
        record = {"image": str(relative), "baseline": str(expected), "status": "missing"}
        if not expected.is_file():
            records.append(record)
            continue
        actual_image = Image.open(current).convert("RGB")
        expected_image = Image.open(expected).convert("RGB")
        if actual_image.size != expected_image.size:
            record.update(
                status="size-mismatch",
                current_size=list(actual_image.size),
                baseline_size=list(expected_image.size),
            )
            records.append(record)
            continue
        difference = ImageChops.difference(actual_image, expected_image)
        changed_mask = difference.convert("L").point(lambda value: 255 if value else 0)
        changed = sum(changed_mask.histogram()[1:])
        total = actual_image.width * actual_image.height
        target = diff_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        difference.point(lambda value: min(255, value * 4)).save(target)
        record.update(
            status="changed" if changed else "identical",
            changed_pixels=changed,
            changed_percent=round(changed * 100 / total, 4),
            bounding_box=list(difference.getbbox()) if difference.getbbox() else None,
            diff=str(target.relative_to(output)),
        )
        records.append(record)
    summary = {
        "baseline": str(baseline.resolve()),
        "compared": len(records),
        "changed": sum(record["status"] == "changed" for record in records),
        "missing": sum(record["status"] == "missing" for record in records),
        "images": records,
    }
    diff_root.mkdir(parents=True, exist_ok=True)
    (diff_root / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / ".tmp-ui" / "rpgmaker-workflow",
    )
    parser.add_argument("--sizes", default="1440x900,1280x720")
    parser.add_argument("--font-scales", default="1.0")
    parser.add_argument(
        "--states",
        default="ready",
        help="Comma-separated: ready,empty,busy,warning,error,complete,disabled",
    )
    parser.add_argument("--overlay", action="store_true")
    parser.add_argument(
        "--baseline",
        type=Path,
        help="Optional prior capture root to compare against",
    )
    args = parser.parse_args()
    states = [item.strip() for item in args.states.split(",") if item.strip()]
    capture(
        args.output,
        _parse_sizes(args.sizes),
        _parse_scales(args.font_scales),
        args.overlay,
        states,
    )
    if args.baseline:
        summary = compare_captures(args.output, args.baseline)
        print(
            f"Compared {summary['compared']} image(s): "
            f"{summary['changed']} changed, {summary['missing']} missing"
        )
    print(f"Workflow captures written to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
