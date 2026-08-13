#!/usr/bin/env python3
"""Build sanitized, annotated screenshots used by the in-app Beginner's Guide.

The images come from real Qt widgets populated only with deterministic fixture
data. No production action is clicked and no user configuration is read.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image, ImageDraw, ImageFont
from PyQt5.QtCore import QPoint, QSettings, Qt
from PyQt5.QtGui import QFont, QImage
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QToolButton,
    QWidget,
)

from gui.theme import COLORS, apply_application_theme
from scripts.capture_workflow_ui import _build_host, _seed_ready_fixture


@dataclass(frozen=True)
class Callout:
    widget: QWidget
    label: str


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _find_button(root: QWidget, text: str) -> QWidget:
    for button_type in (QPushButton, QToolButton):
        for button in root.findChildren(button_type):
            if text.casefold() in button.text().casefold():
                return button
    raise LookupError(f"button not found: {text}")


def _scroll_to(workflow: QWidget, target: QWidget, top_margin: int = 130) -> None:
    page = workflow._step_tabs.currentWidget()
    scroll = page.findChild(QScrollArea, "workflowPageScroll")
    if scroll is None or scroll.widget() is None:
        raise RuntimeError("current workflow page has no scroll area")
    target_y = target.mapTo(scroll.widget(), QPoint(0, 0)).y()
    scroll.verticalScrollBar().setValue(max(0, target_y - top_margin))


def _capture_widget(widget: QWidget) -> Image.Image:
    pixmap = widget.grab()
    image = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
    ptr = image.bits()
    ptr.setsize(image.byteCount())
    return Image.frombytes(
        "RGBA",
        (image.width(), image.height()),
        bytes(ptr),
        "raw",
        "RGBA",
        image.bytesPerLine(),
        1,
    ).copy()


def _wrap_labels(labels: list[str], width: int, font: ImageFont.ImageFont) -> list[str]:
    lines: list[str] = []
    current = ""
    for index, label in enumerate(labels, start=1):
        item = f"{index}  {label}"
        candidate = f"{current}     {item}" if current else item
        if current and font.getlength(candidate) > width:
            lines.append(current)
            current = item
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _annotate(
    source: Image.Image,
    host: QWidget,
    title: str,
    callouts: list[Callout],
    crops: tuple[tuple[int, int, int, int], ...],
    output: Path,
) -> None:
    widths = {right - left for left, _top, right, _bottom in crops}
    if len(widths) != 1:
        raise ValueError("stitched screenshot crops must have equal widths")
    crop_width = widths.pop()
    crop_height = sum(bottom - top for _left, top, _right, bottom in crops)
    screenshot = Image.new("RGB", (crop_width, crop_height), COLORS.chrome)
    crop_offsets: list[tuple[tuple[int, int, int, int], int]] = []
    offset = 0
    for crop in crops:
        left, top, right, bottom = crop
        screenshot.paste(source.crop(crop).convert("RGB"), (0, offset))
        crop_offsets.append((crop, offset))
        offset += bottom - top

    def map_to_screenshot(x: int, y: int) -> tuple[int, int]:
        for (left, top, right, bottom), target_y in crop_offsets:
            if left <= x < right and top <= y < bottom:
                return x - left, target_y + y - top
        raise ValueError(f"callout origin ({x}, {y}) is outside the screenshot crops")

    label_font = _font(19, bold=True)
    title_font = _font(24, bold=True)
    lines = _wrap_labels([callout.label for callout in callouts], screenshot.width - 48, label_font)
    banner_height = 58 + 31 * len(lines)
    canvas = Image.new(
        "RGB",
        (screenshot.width, screenshot.height + banner_height),
        COLORS.chrome,
    )
    canvas.paste(screenshot, (0, banner_height))
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.text((24, 14), title, fill=COLORS.text_primary, font=title_font)
    for line_index, line in enumerate(lines):
        draw.text(
            (24, 50 + line_index * 31),
            line,
            fill=COLORS.text_secondary,
            font=label_font,
        )

    accent = (74, 181, 255, 255)
    for number, callout in enumerate(callouts, start=1):
        origin = callout.widget.mapTo(host, QPoint(0, 0))
        x, y = map_to_screenshot(origin.x(), origin.y())
        y += banner_height
        width = callout.widget.width()
        height = callout.widget.height()
        pad = 5
        draw.rounded_rectangle(
            (x - pad, y - pad, x + width + pad, y + height + pad),
            radius=8,
            outline=accent,
            width=4,
        )
        radius = 17
        circle_x = max(radius + 3, x - pad)
        circle_y = max(banner_height + radius + 3, y - pad)
        draw.ellipse(
            (circle_x - radius, circle_y - radius, circle_x + radius, circle_y + radius),
            fill=accent,
            outline=(255, 255, 255, 255),
            width=2,
        )
        number_text = str(number)
        box = draw.textbbox((0, 0), number_text, font=label_font)
        draw.text(
            (circle_x - (box[2] - box[0]) / 2, circle_y - (box[3] - box[1]) / 2 - 2),
            number_text,
            fill=(10, 25, 36, 255),
            font=label_font,
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, "PNG", optimize=True)


def _build_workflow_images(app: QApplication, output: Path, temp_root: Path) -> None:
    settings = QSettings(str(temp_root / "workflow.ini"), QSettings.IniFormat)
    with patch("util.translation._load_litellm_pricing", return_value={}):
        host, workflow = _build_host(settings)
    _seed_ready_fixture(workflow)

    window = QMainWindow()
    window.setCentralWidget(host)
    window.resize(1000, 760)
    window.show()
    for _ in range(5):
        app.processEvents()
    _seed_ready_fixture(workflow)
    app.processEvents()

    specs = (
        (
            0,
            "Project & Files",
            "workflow-project.png",
            (workflow.folder_edit, "Choose the working game folder"),
            (workflow.file_list, "Select the database and one early map"),
        ),
        (
            2,
            "Speakers & Guidance",
            "workflow-setup.png",
            (workflow.speaker_collect_names_btn, "Collect names first"),
            (workflow.speaker_copy_setup_btn, "Copy the setup instructions second"),
        ),
        (
            3,
            "Translation · Phase 1",
            "workflow-translate.png",
            (workflow._tl_mode_combo, "Use Normal Translate for the first test"),
            (workflow._run_p0_btn, "Translate the database"),
            (workflow._run_p1_btn, "Translate dialogue and choices"),
        ),
        (
            5,
            "Export to Game",
            "workflow-export.png",
            (_find_button(workflow, "Export selected files"), "Export only the selected test files"),
        ),
        (
            6,
            "Rewrap Game Data",
            "workflow-rewrap.png",
            (workflow.rewrap_only_over_limit_cb, "Keep the over-limit-only safeguard enabled"),
            (workflow.rewrap_scan_btn, "Preview before writing"),
            (workflow.rewrap_apply_btn, "Apply only after review"),
        ),
    )

    for step, title, filename, *pairs in specs:
        workflow._step_tabs.setCurrentIndex(step)
        workflow._step_rail.set_current(step)
        app.processEvents()
        callouts = [Callout(widget, label) for widget, label in pairs]
        if step == 2:
            _scroll_to(workflow, workflow.speaker_setup_hint, top_margin=55)
        elif step == 3:
            _scroll_to(workflow, workflow._run_p1_btn, top_margin=430)
        elif step == 6:
            workflow.rewrap_scan_btn.setEnabled(True)
            workflow.rewrap_apply_btn.setEnabled(True)
            workflow.rewrap_status_label.setText(
                "4 of 5 files selected · preview changes before applying"
            )
            _scroll_to(workflow, workflow.rewrap_scan_btn, top_margin=360)
        app.processEvents()
        _annotate(
            _capture_widget(window),
            window,
            title,
            callouts,
            ((0, 48, 990, 570),),
            output / filename,
        )

    window.close()
    workflow.close()
    app.processEvents()


def _build_config_image(app: QApplication, output: Path, temp_root: Path) -> None:
    from gui.config_tab import ConfigTab
    from util import api_keys

    env_path = temp_root / ".env"
    env_path.write_text(
        "api=https://api.openai.com/v1\n"
        "model=gpt-5.6-sol\n"
        "language=English\n",
        encoding="utf-8",
    )
    vault_path = temp_root / "api_keys.json"
    api_keys.save_vault(
        {
            "active": "Tutorial OpenAI key",
            "keys": {
                "Tutorial OpenAI key": {
                    "secret": "sanitized-fixture-secret",
                    "endpoint": "https://api.openai.com/v1",
                    "keyless": False,
                }
            },
        },
        vault_path,
    )

    previous_cwd = Path.cwd()
    os.chdir(temp_root)
    try:
        with (
            patch.object(api_keys, "API_KEYS_PATH", vault_path),
            patch.object(ConfigTab, "fetch_models", lambda self, silent=False, **kwargs: None),
        ):
            config = ConfigTab()
            config.resize(1200, 900)
            config.show()
            for _ in range(4):
                app.processEvents()
            config.api_url_edit.setCursorPosition(0)
            model_edit = config.model_combo.lineEdit()
            if model_edit is not None:
                model_edit.setCursorPosition(0)
            config.setFocus(Qt.OtherFocusReason)
            app.processEvents()
            save = _find_button(config, "Save changes")
            callouts = [
                Callout(config.api_url_preset_btn, "Choose the AI company preset"),
                Callout(config.api_key_combo, "Select or add the saved key"),
                Callout(config.model_combo, "Choose the translation model"),
                Callout(save, "Save changes"),
            ]
            api_card = config._general_cards_by_title["🔑 API Configuration"]
            api_origin = api_card.mapTo(config, QPoint(0, 0))
            save_origin = save.mapTo(config, QPoint(0, 0))
            left = 10
            right = config.width() - 10
            top_crop = (
                left,
                max(0, api_origin.y() - 62),
                right,
                api_origin.y() + api_card.height() + 14,
            )
            action_crop = (
                left,
                max(0, save_origin.y() - 16),
                right,
                min(config.height(), save_origin.y() + save.height() + 10),
            )
            _annotate(
                _capture_widget(config),
                config,
                "Configuration · General Settings",
                callouts,
                (top_crop, action_crop),
                output / "configuration-api.png",
            )
            config.close()
            app.processEvents()
    finally:
        os.chdir(previous_cwd)


def build(output: Path) -> None:
    output = output.resolve()
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    apply_application_theme(app)
    app.setFont(QFont("Segoe UI", 9))
    with tempfile.TemporaryDirectory(prefix="dazedtl-tutorial-capture-") as raw:
        temp_root = Path(raw)
        _build_config_image(app, output, temp_root)
        _build_workflow_images(app, output, temp_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "help" / "images",
    )
    args = parser.parse_args()
    build(args.output)
    print(f"Tutorial screenshots written to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
