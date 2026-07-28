"""Sidebar page for safely migrating translated games to newer versions."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from util.version_update import (
    ConflictResolution,
    RecoveryStatus,
    UpdateAction,
    apply_in_place_update,
    apply_staged_update,
    detect_update_profile,
    discover_original_source,
    scan_version_update,
)
from util.version_update.service import (
    PROFILE_AUTO,
    PROFILE_GENERIC,
    PROFILE_RPGMAKER_MVMZ,
)


_PAGE_STYLE = """
QWidget#versionUpdatePage, QWidget#versionUpdateContent {
    background-color:#2b2b2b; color:#d4d4d4;
}
QLabel { background-color:transparent; color:#d4d4d4; }
QRadioButton { background-color:transparent; color:#d4d4d4; spacing:7px; }
QRadioButton::indicator {
    width:14px; height:14px; border:1px solid #808080;
    border-radius:7px; background-color:#303033;
}
QRadioButton::indicator:checked {
    border-color:#61b7f3; background-color:#007acc;
}
QScrollArea#versionUpdateScroll { background-color:#2b2b2b; border:none; }
QGroupBox#versionUpdateCard {
    background-color:#252526;
    border:1px solid #444444;
    border-radius:7px;
    margin-top:14px;
    padding-top:10px;
    font-weight:normal;
    color:#dcdcdc;
}
QGroupBox#versionUpdateCard::title {
    subcontrol-origin:margin;
    subcontrol-position:top left;
    left:14px;
    padding:2px 7px;
    background-color:#252526;
    color:#4daafc;
    font-weight:bold;
}
QLineEdit, QComboBox, QTextEdit, QTreeWidget {
    background-color:#303033; color:#e2e2e2; border:1px solid #505050;
    border-radius:4px; padding:5px 8px;
}
QLineEdit, QComboBox { min-height:24px; }
QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QTreeWidget:focus {
    border-color:#007acc;
}
QComboBox::drop-down {
    width:28px; border:none; border-left:1px solid #505050;
    background-color:#3a3a3d;
}
QComboBox QAbstractItemView {
    background-color:#303033; color:#e2e2e2;
    selection-background-color:#007acc;
}
QTreeWidget::item:selected { background-color:#264f78; color:#ffffff; }
QTreeWidget { alternate-background-color:#29292c; }
QHeaderView::section {
    background-color:#3a3a3d; color:#e5e5e5; padding:7px 8px;
    border:none; border-right:1px solid #505050;
}
QPushButton {
    background-color:#333337; color:#e8e8e8; border:1px solid #555555;
    border-radius:4px; padding:7px 12px; min-height:20px; font-weight:bold;
}
QPushButton:hover { background-color:#3e3e42; border-color:#007acc; }
QPushButton:pressed { background-color:#264f78; }
QPushButton:disabled { color:#707070; background-color:#2b2b2e; border-color:#414141; }
QWidget#versionUpdateActionBar, QWidget#versionUpdateResolutionBar {
    background-color:#252526; border:1px solid #414141; border-radius:6px;
}
QLabel#versionUpdateStatus {
    color:#b8b8b8; padding:0 4px;
}
QProgressBar {
    background-color:#303033; border:1px solid #505050;
    border-radius:4px; text-align:center; min-height:20px; color:#d4d4d4;
}
QProgressBar::chunk { background-color:#007acc; }
QSplitter::handle { background-color:#414141; }
QSplitter::handle:hover { background-color:#007acc; }
QScrollBar:vertical {
    background-color:#2b2b2b; width:12px; border:none;
}
QScrollBar::handle:vertical {
    background-color:#555555; border-radius:5px; min-height:24px; margin:2px;
}
QScrollBar::handle:vertical:hover { background-color:#007acc; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar:horizontal {
    background-color:#2b2b2b; height:12px; border:none;
}
QScrollBar::handle:horizontal {
    background-color:#555555; border-radius:5px; min-width:24px; margin:2px;
}
QScrollBar::handle:horizontal:hover { background-color:#007acc; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }
"""


_UNRESOLVED = object()
_SEMANTIC_PATH_TOKEN = re.compile(r"(?:^|\.)([^.\[\]]+)|\[(\d+)\]")


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or singular + "s")


def _split_semantic_detail(detail: str) -> tuple[str, str]:
    path, separator, reason = detail.partition(": ")
    if separator and path.startswith("$"):
        return path, reason
    return "", detail


def _semantic_path_tokens(path: str) -> list[str | int]:
    if not path.startswith("$"):
        return []
    tokens: list[str | int] = []
    for match in _SEMANTIC_PATH_TOKEN.finditer(path[1:]):
        name, index = match.groups()
        tokens.append(int(index) if index is not None else name)
    return tokens


def _selector_value(token: str, prefix: str) -> str:
    return token[len(prefix) :]


def _resolve_semantic_value(document: Any, path: str) -> Any:
    value = document
    for token in _semantic_path_tokens(path):
        if token == "embedded JSON":
            if not isinstance(value, str):
                return _UNRESOLVED
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return _UNRESOLVED
            continue
        if isinstance(token, int):
            if not isinstance(value, list) or token >= len(value):
                return _UNRESOLVED
            value = value[token]
            continue
        if isinstance(value, list) and token.startswith("id="):
            wanted = _selector_value(token, "id=")
            value = next(
                (
                    item
                    for item in value
                    if isinstance(item, dict) and str(item.get("id")) == wanted
                ),
                _UNRESOLVED,
            )
            if value is _UNRESOLVED:
                return value
            continue
        if isinstance(value, list) and token.startswith("plugin="):
            wanted = _selector_value(token, "plugin=")
            value = next(
                (
                    item
                    for item in value
                    if isinstance(item, dict) and item.get("name") == wanted
                ),
                _UNRESOLVED,
            )
            if value is _UNRESOLVED:
                return value
            continue
        if not isinstance(value, dict) or token not in value:
            return _UNRESOLVED
        value = value[token]
    return value


def _decode_decision_document(decision) -> Any:
    content = decision.generated_content
    if content is None and decision.new and decision.new.source_path:
        try:
            content = decision.new.source_path.read_bytes()
        except OSError:
            return None
    if content is None:
        return None
    try:
        text = content.decode("utf-8-sig")
        if decision.relative_path.casefold().endswith("js/plugins.js"):
            marker = re.search(r"\bvar\s+\$plugins\s*=", text)
            if marker is None:
                return None
            text = text[marker.end() :].strip().removesuffix(";").rstrip()
        return json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _command_for_path(document: Any, path: str) -> dict[str, Any] | None:
    tokens = _semantic_path_tokens(path)
    try:
        list_index = tokens.index("list")
    except ValueError:
        return None
    if list_index + 1 >= len(tokens) or not isinstance(tokens[list_index + 1], int):
        return None
    command_path = "$"
    for token in tokens[: list_index + 2]:
        command_path += f"[{token}]" if isinstance(token, int) else f".{token}"
    command = _resolve_semantic_value(document, command_path)
    return command if isinstance(command, dict) else None


def _human_semantic_location(path: str, document: Any) -> str:
    tokens = _semantic_path_tokens(path)
    if not tokens:
        return path or "File-level change"
    parts: list[str] = []

    plugin = next(
        (token for token in tokens if isinstance(token, str) and token.startswith("plugin=")),
        None,
    )
    if plugin:
        parts.append(f'Plugin “{_selector_value(plugin, "plugin=")}”')

    event_id = None
    if "events" in tokens:
        event_index = tokens.index("events")
        if event_index + 1 < len(tokens):
            selector = tokens[event_index + 1]
            if isinstance(selector, str) and selector.startswith("id="):
                event_id = _selector_value(selector, "id=")
                event_name = ""
                if isinstance(document, dict):
                    events = document.get("events")
                    if isinstance(events, list):
                        event = next(
                            (
                                item
                                for item in events
                                if isinstance(item, dict)
                                and str(item.get("id")) == event_id
                            ),
                            None,
                        )
                        if isinstance(event, dict) and isinstance(event.get("name"), str):
                            event_name = event["name"].strip()
                parts.append(
                    f'Event {event_id} “{event_name}”' if event_name else f"Event {event_id}"
                )

    if "pages" in tokens:
        index = tokens.index("pages")
        if index + 1 < len(tokens) and isinstance(tokens[index + 1], int):
            parts.append(f"Page {tokens[index + 1] + 1}")

    command = _command_for_path(document, path)
    if "list" in tokens:
        index = tokens.index("list")
        if index + 1 < len(tokens) and isinstance(tokens[index + 1], int):
            code = command.get("code") if command else None
            command_label = {
                101: "Message",
                102: "Choices",
                401: "Dialogue",
                405: "Scrolling text",
                408: "Comment",
            }.get(code, "Event command")
            parts.append(f"{command_label} {tokens[index + 1] + 1}")

    root_id = next(
        (
            _selector_value(token, "id=")
            for token in tokens
            if isinstance(token, str) and token.startswith("id=")
        ),
        None,
    )
    if root_id is not None and event_id is None:
        parts.append(f"Entry {root_id}")

    field_names = {
        "description": "Description",
        "displayName": "Display name",
        "gameTitle": "Game title",
        "help": "Help text",
        "message": "Message",
        "name": "Name",
        "nickname": "Nickname",
        "note": "Note",
        "profile": "Profile",
    }
    for token in reversed(tokens):
        if isinstance(token, str) and token in field_names:
            parts.append(field_names[token])
            break
    return " · ".join(parts) if parts else path


def _value_preview(value: Any) -> str:
    if isinstance(value, dict) and isinstance(value.get("parameters"), list):
        parameters = value["parameters"]
        value = parameters[0] if parameters else _UNRESOLVED
    if value is _UNRESOLVED or value is None:
        return ""
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        text = " / ".join(value)
    elif isinstance(value, (str, int, float, bool)):
        text = str(value)
    else:
        return ""
    text = " ↵ ".join(part.strip() for part in text.splitlines()).strip()
    return text if len(text) <= 180 else text[:177] + "…"


def _resolution_label(resolution: ConflictResolution | None) -> str:
    return {
        ConflictResolution.USE_PROPOSED: "Merge New + Local Changes",
        ConflictResolution.USE_NEW: "Use New",
        ConflictResolution.KEEP_CURRENT: "Keep Current",
        ConflictResolution.USE_MERGED_FILE: "Use Manually Merged File",
        None: "No choice selected",
    }[resolution]


def _detail_item_label(reason: str) -> str:
    return {
        "source text is unchanged": "Kept translation",
        "source text changed upstream": "Official text changed",
        "translated source text changed upstream": "Translation must be refreshed",
        "new upstream source": "New official text",
        "new upstream event command": "New official command",
        "an upstream command matches a command removed by the translator": (
            "Restored official command"
        ),
        "both translator and upstream changed this value": "Changed on both sides",
        "upstream deleted a translator-modified value": "Local edit removed upstream",
        "translator removed a value changed upstream": "Locally removed value changed upstream",
        "translator-added value collides with new upstream value": "Colliding local addition",
        "translator-added structured value": "Kept local addition",
    }.get(reason, "Affected content")


def _decision_outcome(decision) -> str:
    if decision.action == UpdateAction.CONFLICT:
        return {
            ConflictResolution.USE_PROPOSED: (
                "Use the new official structure and carry forward compatible local edits."
            ),
            ConflictResolution.USE_NEW: (
                "Replace the current file with the new official file."
            ),
            ConflictResolution.KEEP_CURRENT: (
                "Keep the current file and skip the official replacement for this file."
            ),
            ConflictResolution.USE_MERGED_FILE: "Use the manually reviewed merged file.",
            None: "Wait for you to choose which version of this file to use.",
        }[decision.resolution]
    return {
        UpdateAction.KEEP: "Keep the file because it already matches the intended result.",
        UpdateAction.PRESERVE_TRANSLATED: (
            "Keep the current translated file because its official source did not change."
        ),
        UpdateAction.USE_NEW: "Replace the current file with the new official file.",
        UpdateAction.ADD_NEW: "Add this file from the new official version.",
        UpdateAction.PRESERVE_ADDED: "Keep this locally added file.",
        UpdateAction.DELETE: "Remove this file because it is absent from the intended result.",
        UpdateAction.MERGE_TEXT: "Combine non-overlapping official and local text edits.",
        UpdateAction.MERGE_SEMANTIC: (
            "Use the new official structure and carry forward compatible local edits."
        ),
        UpdateAction.PROTECT_CURRENT: "Leave this protected local file unchanged.",
    }[decision.action]


def _format_decision_details(decision) -> tuple[str, str]:
    entries = [_split_semantic_detail(detail) for detail in decision.details]
    reason_counts = Counter(reason for _path, reason in entries)
    automatic_review = (
        decision.action == UpdateAction.CONFLICT
        and decision.resolution is not None
        and decision.resolution_is_automatic
    )
    if decision.blocking:
        status = "Choice required"
    elif decision.translation_at_risk:
        status = "Local changes at risk"
    elif automatic_review or decision.needs_review:
        status = "Automatic merge — review recommended"
    elif decision.needs_translation:
        status = "Ready — translation needed"
    else:
        status = "Ready"

    lines = [decision.relative_path, status]
    recovery_explanation = {
        RecoveryStatus.DEFINITE_REVERT: (
            "The complete current file matches the previous official version while the selected "
            "official build differs. This is a definite full-file revert."
        ),
        RecoveryStatus.POSSIBLE_REVERT: (
            "The current file matches neither official version. It may contain a partial revert "
            "or legitimate edits made after the update, so review the proposed result."
        ),
        RecoveryStatus.ALREADY_PRESENT: (
            "The current file already contains the official file change from this update."
        ),
        None: "",
    }[decision.recovery_status]
    if recovery_explanation:
        lines.extend(["", "Recovery finding", f"• {recovery_explanation}"])
    lines.extend(["", "What will happen", f"• {_decision_outcome(decision)}"])
    if decision.preserved_translations:
        count = decision.preserved_translations
        lines.append(f"• Keep {count} existing {_plural(count, 'translation')}.")
    if decision.needs_translation:
        count = decision.needs_translation
        lines.append(
            f"• Leave {count} new or changed text {_plural(count, 'segment')} "
            "ready for translation."
        )
    restored = reason_counts[
        "an upstream command matches a command removed by the translator"
    ]
    if restored:
        lines.append(
            f"• Restore {restored} event {_plural(restored, 'command')} that "
            f"{_plural(restored, 'was', 'were')} removed locally."
        )
    new_commands = reason_counts["new upstream event command"]
    if new_commands:
        lines.append(
            f"• Add {new_commands} new official event {_plural(new_commands, 'command')}."
        )
    local_additions = reason_counts["translator-added structured value"]
    if local_additions:
        lines.append(
            f"• Keep {local_additions} local structured {_plural(local_additions, 'addition')}."
        )

    attention: list[str] = []
    if decision.translation_at_risk:
        attention.append(
            "The selected result does not carry over this file's differing local changes."
        )
    if restored:
        attention.append(
            "Those locally removed commands still exist in the new official version, so the "
            "recommended merge restores them."
        )
    changed_layout = reason_counts[
        "translator changed event-command structure; manual file review is required"
    ]
    if changed_layout:
        attention.append("The local version changed the event-command layout.")
    both_changed = reason_counts["both translator and upstream changed this value"]
    if both_changed:
        attention.append(
            f"Both versions changed {both_changed} {_plural(both_changed, 'value')}; the "
            "proposed merge uses the official value there."
        )
    removed_local = reason_counts["upstream deleted a translator-modified value"]
    if removed_local:
        attention.append(
            f"The official update removed {removed_local} locally edited "
            f"{_plural(removed_local, 'value')}."
        )
    removed_then_changed = reason_counts["translator removed a value changed upstream"]
    if removed_then_changed:
        attention.append(
            f"The official update changed {removed_then_changed} locally removed "
            f"{_plural(removed_then_changed, 'value')}."
        )
    collisions = reason_counts["translator-added value collides with new upstream value"]
    if collisions:
        attention.append(
            f"{collisions} local {_plural(collisions, 'addition')} now conflicts "
            "with official content."
        )
    if decision.needs_review and not attention:
        attention.append("Review the automatically merged file before releasing the update.")

    if attention:
        lines.extend(["", "What needs your attention"])
        lines.extend(f"• {item}" for item in attention)
    elif not decision.blocking:
        lines.extend(["", "No manual merge choice is required."])

    if decision.recommended_resolution or decision.resolution or decision.blocking:
        lines.extend(["", "Choice"])
        if decision.resolution:
            source = (
                "Selected automatically"
                if decision.resolution_is_automatic
                else "Your selection"
            )
            lines.append(f"{source}: {_resolution_label(decision.resolution)}")
        else:
            lines.append("Choose a result using the buttons below.")
        if (
            decision.recommended_resolution
            and decision.recommended_resolution != decision.resolution
        ):
            lines.append(f"Recommended: {_resolution_label(decision.recommended_resolution)}")

    document = _decode_decision_document(decision)
    actionable = [entry for entry in entries if entry[1] != "source text is unchanged"]
    preserved = [entry for entry in entries if entry[1] == "source text is unchanged"]
    displayed = actionable[:6]
    displayed.extend(preserved[: max(0, 8 - len(displayed))])
    if displayed:
        lines.extend(["", "Affected content"])
        for path, reason in displayed:
            location = _human_semantic_location(path, document)
            lines.append(f"• {_detail_item_label(reason)} — {location}")
            preview = _value_preview(_resolve_semantic_value(document, path))
            if preview:
                prefix = "Kept" if reason == "source text is unchanged" else "Result"
                lines.append(f"  {prefix}: {preview}")
        remaining = len(entries) - len(displayed)
        if remaining > 0:
            lines.append(
                f"• {remaining} additional {_plural(remaining, 'change')} available "
                "in the technical log."
            )

    technical = [
        decision.relative_path,
        f"Action id: {decision.action.value}",
        f"File kind: {decision.kind.value}",
        f"Engine reason: {decision.reason}",
        f"Needs translation: {decision.needs_translation}",
        f"Preserved translations: {decision.preserved_translations}",
        f"Recovery status: {decision.recovery_status.value if decision.recovery_status else 'none'}",
    ]
    if decision.resolution:
        source = "automatic" if decision.resolution_is_automatic else "manual"
        technical.append(f"Resolution id: {decision.resolution.value} ({source})")
    if decision.details:
        technical.extend(["", "Merge entries:", *decision.details[:200]])
        if len(decision.details) > 200:
            technical.append(f"… {len(decision.details) - 200} additional entries")
    return "\n".join(lines), "\n".join(technical)


class _ScanWorker(QThread):
    progress = pyqtSignal(str, int, int, str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, kwargs: dict):
        super().__init__()
        self.kwargs = kwargs

    def run(self):
        try:
            def emit_progress(stage: str, current: int, total: int, detail: str):
                if self.isInterruptionRequested():
                    raise InterruptedError("Version Update scan cancelled")
                self.progress.emit(stage, current, total, detail)

            plan = scan_version_update(progress=emit_progress, **self.kwargs)
            self.done.emit(plan)
        except Exception as exc:
            self.failed.emit(str(exc))


class _ApplyWorker(QThread):
    progress = pyqtSignal(int, int, str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, plan, output_root: str, *, in_place: bool = False):
        super().__init__()
        self.plan = plan
        self.output_root = output_root
        self.in_place = in_place

    def run(self):
        try:
            progress = lambda current, total, detail: self.progress.emit(
                current, total, detail
            )
            if self.in_place:
                result = apply_in_place_update(self.plan, progress=progress)
            else:
                result = apply_staged_update(
                    self.plan,
                    self.output_root,
                    progress=progress,
                )
            self.done.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class VersionUpdateTab(QWidget):
    """Scan, review, and create a staged updated translation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("versionUpdatePage")
        self._plan = None
        self._scan_worker = None
        self._apply_worker = None
        self._items: dict[int, QTreeWidgetItem] = {}
        self.setStyleSheet(_PAGE_STYLE)
        self._build_ui()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("versionUpdateScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.viewport().setStyleSheet("background-color:#2b2b2b;")

        content = QWidget()
        content.setObjectName("versionUpdateContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 22)
        layout.setSpacing(14)
        scroll.setWidget(content)
        root_layout.addWidget(scroll)

        title = QLabel("Version Update")
        title.setStyleSheet(
            "font-size:24px;font-weight:bold;color:#f2f2f2;padding:0 0 2px 2px;"
        )
        layout.addWidget(title)
        subtitle = QLabel(
            "Migrate a translated game to a newer official version. Scanning is read-only; "
            "create a separate copy or transactionally replace the translation with a backup."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            "color:#a8a8a8;font-size:13px;padding:0 2px 2px 2px;"
        )
        layout.addWidget(subtitle)

        select_group = QGroupBox("1 — Select old, translated, and new game states")
        select_group.setObjectName("versionUpdateCard")
        form = QFormLayout(select_group)
        form.setContentsMargins(18, 22, 18, 16)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setLabelAlignment(Qt.AlignRight)
        self.current_edit = self._folder_row(
            form, "Current translated:", "Folder containing the working translation"
        )
        self.current_edit.editingFinished.connect(self._refresh_detection)
        self.current_edit.textChanged.connect(self._update_in_place_target)
        self.new_edit = self._folder_row(
            form, "New official:", "Clean folder for the newer official game version"
        )
        self.new_edit.editingFinished.connect(self._refresh_detection)
        self.old_edit = self._folder_row(
            form,
            "Old official (optional):",
            "Clean old version; otherwise a baseline or Git original branch is used",
        )
        self.old_edit.editingFinished.connect(self._refresh_detection)

        version_row = QHBoxLayout()
        self.old_version_edit = QLineEdit()
        self.old_version_edit.setPlaceholderText("v1.00")
        self.old_version_edit.setMaximumWidth(180)
        self.new_version_edit = QLineEdit()
        self.new_version_edit.setPlaceholderText("v1.03")
        self.new_version_edit.setMaximumWidth(180)
        version_row.addWidget(QLabel("From"))
        version_row.addWidget(self.old_version_edit)
        version_row.addWidget(QLabel("to"))
        version_row.addWidget(self.new_version_edit)
        version_row.addStretch()
        form.addRow("Version labels:", version_row)

        self.profile_combo = QComboBox()
        self.profile_combo.addItem("Auto-detect", PROFILE_AUTO)
        self.profile_combo.addItem("RPG Maker MV/MZ", PROFILE_RPGMAKER_MVMZ)
        self.profile_combo.addItem("Generic / Files Only", PROFILE_GENERIC)
        self.profile_combo.setMaximumWidth(360)
        form.addRow("Update profile:", self.profile_combo)
        self.detection_label = QLabel("Select current and new game folders.")
        self.detection_label.setWordWrap(True)
        self.detection_label.setStyleSheet("color:#9cdcfe;")
        form.addRow("Detection:", self.detection_label)
        self.baseline_label = QLabel("")
        self.baseline_label.setWordWrap(True)
        form.addRow("Baseline:", self.baseline_label)
        layout.addWidget(select_group)

        action_bar = QWidget()
        action_bar.setObjectName("versionUpdateActionBar")
        action_row = QHBoxLayout(action_bar)
        action_row.setContentsMargins(12, 9, 12, 9)
        action_row.setSpacing(10)
        self.scan_btn = QPushButton("Scan Update")
        self.scan_btn.setStyleSheet(
            "QPushButton{background-color:#0e639c;border-color:#168bd0;color:white;}"
            "QPushButton:hover{background-color:#1177b5;}"
            "QPushButton:disabled{background-color:#2b2b2e;color:#707070;"
            "border-color:#414141;}"
        )
        self.scan_btn.clicked.connect(self._scan)
        action_row.addWidget(self.scan_btn)
        self.cancel_scan_btn = QPushButton("Cancel Scan")
        self.cancel_scan_btn.setEnabled(False)
        self.cancel_scan_btn.clicked.connect(self._cancel_scan)
        action_row.addWidget(self.cancel_scan_btn)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        action_row.addWidget(self.progress, 1)
        self.progress_label = QLabel("Ready")
        self.progress_label.setObjectName("versionUpdateStatus")
        self.progress_label.setMinimumWidth(150)
        self.progress_label.setMaximumWidth(320)
        action_row.addWidget(self.progress_label)
        layout.addWidget(action_bar)

        review_group = QGroupBox("3 — Optional: Review or override local-file decisions")
        review_group.setObjectName("versionUpdateCard")
        review_group.setMinimumHeight(410)
        review_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        review_layout = QVBoxLayout(review_group)
        review_layout.setContentsMargins(18, 22, 18, 16)
        review_layout.setSpacing(10)
        self.summary_label = QLabel("Run a scan to build the update plan.")
        self.summary_label.setWordWrap(True)
        review_layout.addWidget(self.summary_label)

        policy_label = QLabel(
            "Upstream-first mode includes every new official change. Safe translation and "
            "plugin edits are layered on automatically; uncertain files default to the new "
            "official version and remain in the review queue below."
        )
        policy_label.setWordWrap(True)
        policy_label.setStyleSheet(
            "color:#c8e6c9;background-color:#26382d;border:1px solid #3f684b;"
            "border-radius:5px;padding:8px 10px;"
        )
        review_layout.addWidget(policy_label)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("Show:"))
        self.review_filter = QComboBox()
        self.review_filter.addItem("Needs review", "review")
        self.review_filter.addItem("Recovery findings", "recovery")
        self.review_filter.addItem("Translation at risk", "risk")
        self.review_filter.addItem("Merged automatically", "merged")
        self.review_filter.addItem("Official additions / replacements", "upstream")
        self.review_filter.addItem("All game files", "all")
        self.review_filter.setMinimumWidth(210)
        self.review_filter.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.review_filter)
        self.review_search = QLineEdit()
        self.review_search.setPlaceholderText("Filter by relative path…")
        self.review_search.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.review_search, 1)
        self.apply_recommended_btn = QPushButton("Restore Recommended Choices")
        self.apply_recommended_btn.setToolTip(
            "Use a three-way merge where available; otherwise let the new official file win."
        )
        self.apply_recommended_btn.clicked.connect(self._apply_recommended_to_all)
        self.apply_recommended_btn.setEnabled(False)
        filter_row.addWidget(self.apply_recommended_btn)
        review_layout.addLayout(filter_row)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(5)
        splitter.setChildrenCollapsible(False)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Action", "Relative path", "Kind", "Status"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(1, Qt.AscendingOrder)
        self.tree.setMinimumHeight(270)
        self.tree.setMinimumWidth(480)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tree.currentItemChanged.connect(self._show_selected)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        splitter.addWidget(self.tree)
        details_panel = QWidget()
        details_layout = QVBoxLayout(details_panel)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(7)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumWidth(280)
        self.details.setPlaceholderText("Select a file to see what the update will do.")
        details_layout.addWidget(self.details, 1)
        self.technical_toggle = QPushButton("Show technical merge log")
        self.technical_toggle.setCheckable(True)
        self.technical_toggle.setVisible(False)
        self.technical_toggle.toggled.connect(self._toggle_technical_details)
        details_layout.addWidget(self.technical_toggle)
        self.technical_details = QTextEdit()
        self.technical_details.setReadOnly(True)
        self.technical_details.setMaximumHeight(190)
        self.technical_details.setVisible(False)
        details_layout.addWidget(self.technical_details)
        splitter.addWidget(details_panel)
        splitter.setSizes([760, 360])
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        review_layout.addWidget(splitter, 1)

        resolution_bar = QWidget()
        resolution_bar.setObjectName("versionUpdateResolutionBar")
        resolve_row = QGridLayout(resolution_bar)
        resolve_row.setContentsMargins(12, 9, 12, 9)
        resolve_row.setHorizontalSpacing(8)
        resolve_row.setVerticalSpacing(7)
        self.resolution_label = QLabel(
            "Select one or more review items. Recommended choices are already applied."
        )
        self.resolution_label.setStyleSheet("color:#a8a8a8;font-size:12px;")
        resolve_row.addWidget(self.resolution_label, 0, 0, 1, 2)
        self.use_new_btn = QPushButton("Use New (drop local file changes)")
        self.use_new_btn.clicked.connect(
            lambda: self._resolve_selected(ConflictResolution.USE_NEW)
        )
        resolve_row.addWidget(self.use_new_btn, 1, 0)
        self.use_proposed_btn = QPushButton("Merge New + Local Changes")
        self.use_proposed_btn.clicked.connect(
            lambda: self._resolve_selected(ConflictResolution.USE_PROPOSED)
        )
        resolve_row.addWidget(self.use_proposed_btn, 1, 1)
        self.keep_current_btn = QPushButton("Keep Current (skip this new file)")
        self.keep_current_btn.clicked.connect(
            lambda: self._resolve_selected(ConflictResolution.KEEP_CURRENT)
        )
        resolve_row.addWidget(self.keep_current_btn, 2, 0)
        self.provide_merge_btn = QPushButton("Choose Manually Merged File…")
        self.provide_merge_btn.clicked.connect(self._provide_merged_file)
        resolve_row.addWidget(self.provide_merge_btn, 2, 1)
        for column in range(2):
            resolve_row.setColumnStretch(column, 1)
        review_layout.addWidget(resolution_bar)
        self._set_resolution_buttons(None)

        apply_group = QGroupBox("2 — Create the recommended updated copy")
        apply_group.setObjectName("versionUpdateCard")
        apply_layout = QVBoxLayout(apply_group)
        apply_layout.setContentsMargins(18, 22, 18, 16)
        apply_layout.setSpacing(10)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(18)
        mode_row.addWidget(QLabel("Destination:"))
        self.copy_mode_radio = QRadioButton("Create a separate updated folder")
        self.copy_mode_radio.setChecked(True)
        self.copy_mode_radio.toggled.connect(self._update_output_mode)
        mode_row.addWidget(self.copy_mode_radio)
        self.in_place_mode_radio = QRadioButton(
            "Update the current translated folder (keep rollback backup)"
        )
        self.in_place_mode_radio.toggled.connect(self._update_output_mode)
        mode_row.addWidget(self.in_place_mode_radio)
        mode_row.addStretch(1)
        apply_layout.addLayout(mode_row)
        output_row = QHBoxLayout()
        output_row.setSpacing(10)
        self.output_label = QLabel("Separate output folder:")
        output_row.addWidget(self.output_label)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("A new, non-existing destination folder")
        output_row.addWidget(self.output_edit, 1)
        self.in_place_target_label = QLabel("")
        self.in_place_target_label.setStyleSheet("color:#e2e2e2;padding:5px 8px;")
        self.in_place_target_label.setVisible(False)
        output_row.addWidget(self.in_place_target_label, 1)
        self.output_browse_btn = QPushButton("Browse…")
        self.output_browse_btn.clicked.connect(lambda: self._browse(self.output_edit))
        output_row.addWidget(self.output_browse_btn)
        apply_layout.addLayout(output_row)
        self.safety_label = QLabel(
            "Recommended mode applies the complete official update and carries forward only "
            "local changes proven safe by the old/current/new comparison. You can translate new "
            "text or reconcile flagged files afterward. Inputs are rechecked before writing; "
            "the original folders are never modified."
        )
        self.safety_label.setWordWrap(True)
        self.safety_label.setStyleSheet("color:#d7ba7d;")
        apply_layout.addWidget(self.safety_label)
        apply_row = QHBoxLayout()
        self.apply_btn = QPushButton("Create Recommended Update")
        self.apply_btn.setStyleSheet(
            "QPushButton{background-color:#246b3c;border-color:#3b9658;color:white;}"
            "QPushButton:hover{background-color:#2d7d46;}"
            "QPushButton:disabled{background-color:#2b2b2e;color:#707070;"
            "border-color:#414141;}"
        )
        self.apply_btn.setEnabled(False)
        self.apply_btn.setToolTip(
            "Restore every recommended upstream-first choice and create the updated copy."
        )
        self.apply_btn.clicked.connect(self._apply_recommended)
        apply_row.addWidget(self.apply_btn)
        self.custom_apply_btn = QPushButton("Create with Review Choices")
        self.custom_apply_btn.setToolTip(
            "Create the copy using any manual overrides selected in the review queue."
        )
        self.custom_apply_btn.setEnabled(False)
        self.custom_apply_btn.clicked.connect(self._apply)
        apply_row.addWidget(self.custom_apply_btn)
        self.finish_label = QLabel("")
        self.finish_label.setWordWrap(True)
        apply_row.addStretch(1)
        self.continue_workflow_btn = QPushButton("Continue in Workflow")
        self.continue_workflow_btn.setEnabled(False)
        self.continue_workflow_btn.clicked.connect(self._continue_in_workflow)
        apply_row.addWidget(self.continue_workflow_btn)
        self.open_images_btn = QPushButton("Open Output Images")
        self.open_images_btn.setEnabled(False)
        self.open_images_btn.clicked.connect(self._open_output_images)
        apply_row.addWidget(self.open_images_btn)
        apply_layout.addLayout(apply_row)
        apply_layout.addWidget(self.finish_label)
        layout.addWidget(apply_group)
        layout.addWidget(review_group, 1)
        self._last_output = None
        self._update_output_mode()
        self._refresh_detection()

    def _update_in_place_target(self):
        current = (
            str(self._plan.current_root)
            if self._plan is not None
            else self.current_edit.text().strip()
        )
        self.in_place_target_label.setText(
            current or "Select the current translated folder above"
        )

    def _update_output_mode(self):
        if not hasattr(self, "in_place_mode_radio"):
            return
        in_place = self.in_place_mode_radio.isChecked()
        recovery = bool(self._plan and self._plan.audit_reapply)
        self.output_label.setText(
            "Current translated folder:" if in_place else "Separate output folder:"
        )
        self.output_edit.setVisible(not in_place)
        self.output_browse_btn.setVisible(not in_place)
        self.in_place_target_label.setVisible(in_place)
        self._update_in_place_target()
        if recovery:
            self.apply_btn.setText("Reapply Recovered Changes")
            self.custom_apply_btn.setText("Reapply with Review Choices")
            self.apply_btn.setToolTip(
                "Deliberately reapply every recommended change found by the recovery audit."
            )
            self.custom_apply_btn.setToolTip(
                "Reapply the recovered update using manual overrides from the review queue."
            )
            if in_place:
                self.safety_label.setText(
                    "Recovery audit is read-only. Reapplying builds the recovered result in a "
                    "sibling staging folder first, then replaces the current translated folder "
                    "and keeps its previous contents as a rollback backup. Staged files and RPG "
                    "Maker JSON are verified before the folder swap."
                )
                self.safety_label.setStyleSheet("color:#f0ad4e;")
            else:
                self.safety_label.setText(
                    "Recovery audit is read-only. Reapplying creates a separate recovered copy; "
                    "the current translation and both official source folders remain unchanged. "
                    "Staged files and RPG Maker JSON are verified before publishing the copy."
                )
                self.safety_label.setStyleSheet("color:#d7ba7d;")
            return
        self.apply_btn.setText(
            "Update Translated Game" if in_place else "Create Recommended Update"
        )
        self.custom_apply_btn.setText(
            "Update with Review Choices"
            if in_place
            else "Create with Review Choices"
        )
        self.apply_btn.setToolTip(
            "Restore every recommended upstream-first choice and create the updated copy."
        )
        self.custom_apply_btn.setToolTip(
            "Create the copy using any manual overrides selected in the review queue."
        )
        if in_place:
            self.safety_label.setText(
                "The complete update is built in a sibling staging folder first. Only after "
                "that succeeds is the current translated folder replaced, and its previous "
                "contents are retained beside it as a rollback backup. Close the game and any "
                "editors using this folder before continuing. Staged files and RPG Maker JSON "
                "are verified before the folder swap."
            )
            self.safety_label.setStyleSheet("color:#f0ad4e;")
        else:
            self.safety_label.setText(
                "Recommended mode applies the complete official update and carries forward only "
                "local changes proven safe by the old/current/new comparison. You can translate "
                "new text or reconcile flagged files afterward. Inputs are rechecked before "
                "writing; staged files and RPG Maker JSON are verified before publishing, and "
                "the original folders are never modified."
            )
            self.safety_label.setStyleSheet("color:#d7ba7d;")

    def _folder_row(self, form: QFormLayout, label: str, placeholder: str) -> QLineEdit:
        row = QHBoxLayout()
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        row.addWidget(edit, 1)
        button = QPushButton("Browse…")
        button.setFixedWidth(100)
        button.clicked.connect(lambda _checked=False, target=edit: self._browse(target))
        row.addWidget(button)
        form.addRow(label, row)
        return edit

    def _browse(self, target: QLineEdit):
        start = target.text().strip() or self.current_edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select game folder", start)
        if folder:
            target.setText(folder)
            self._refresh_detection()

    def _refresh_detection(self):
        rows = []
        for label, edit in (("Current", self.current_edit), ("New", self.new_edit)):
            raw = edit.text().strip()
            if raw and Path(raw).is_dir():
                profile, reason = detect_update_profile(raw)
                rows.append(f"{label}: {profile} — {reason}")
        self.detection_label.setText("\n".join(rows) or "Select current and new game folders.")
        current = self.current_edit.text().strip()
        explicit_old = self.old_edit.text().strip()
        project = (
            Path(current) / ".dazedtl" / "version_update" / "project.json"
            if current
            else None
        )
        if explicit_old and Path(explicit_old).is_dir():
            self.baseline_label.setText(
                "Selected old official folder will be used. JSON formatting differences "
                "are normalized during comparison."
            )
            self.baseline_label.setStyleSheet("color:#9cdcfe;")
        elif project and project.is_file():
            self.baseline_label.setText(
                "Saved official-source baseline found; Old official may be left blank. If the "
                "selected build was already applied, Recovery audit runs automatically."
            )
            self.baseline_label.setStyleSheet("color:#6a9955;")
        else:
            git_source = None
            if current and Path(current).is_dir():
                try:
                    git_source = discover_original_source(current)
                except Exception:
                    git_source = None
            if git_source is not None:
                self.baseline_label.setText(
                    f"{git_source.label} found and will be read directly if Old official "
                    "is blank. JSON formatting differences are normalized automatically."
                )
                self.baseline_label.setStyleSheet("color:#6a9955;")
            else:
                self.baseline_label.setText(
                    "No saved baseline or Git original branch found; select Old official "
                    "for this first update."
                )
                self.baseline_label.setStyleSheet("color:#d7ba7d;")

    def _scan(self):
        if self._scan_worker and self._scan_worker.isRunning():
            return
        current = self.current_edit.text().strip()
        new = self.new_edit.text().strip()
        old = self.old_edit.text().strip()
        if not current or not new:
            QMessageBox.warning(
                self,
                "Missing folders",
                "Select current translated and new official folders.",
            )
            return
        kwargs = {
            "current_root": current,
            "new_root": new,
            "old_root": old or None,
            "old_version": self.old_version_edit.text().strip(),
            "new_version": self.new_version_edit.text().strip(),
            "profile_id": self.profile_combo.currentData(),
        }
        if self._plan is not None:
            self._plan.cleanup_temporary_resources()
        self._plan = None
        self._update_output_mode()
        self.tree.clear()
        self.details.clear()
        self.technical_details.clear()
        self.technical_toggle.setChecked(False)
        self.technical_toggle.setVisible(False)
        self.finish_label.clear()
        self._last_output = None
        self.continue_workflow_btn.setEnabled(False)
        self.open_images_btn.setEnabled(False)
        self.apply_btn.setEnabled(False)
        self.custom_apply_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.cancel_scan_btn.setEnabled(True)
        self.progress.setRange(0, 0)
        self.progress_label.setText("Starting scan…")
        worker = _ScanWorker(kwargs)
        worker.progress.connect(self._on_scan_progress)
        worker.done.connect(self._on_scan_done)
        worker.failed.connect(self._on_scan_failed)
        worker.finished.connect(self._release_scan_worker)
        self._scan_worker = worker
        worker.start()

    def _cancel_scan(self):
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.requestInterruption()
            self.progress_label.setText("Cancelling scan…")

    def _on_scan_progress(self, stage: str, current: int, total: int, detail: str):
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(current)
        else:
            self.progress.setRange(0, 0)
        self.progress_label.setText(f"{stage.title()}: {detail}")

    def _on_scan_done(self, plan):
        self._plan = plan
        self._update_output_mode()
        self.review_filter.blockSignals(True)
        target_filter = "recovery" if plan.audit_reapply else "review"
        self.review_filter.setCurrentIndex(self.review_filter.findData(target_filter))
        self.review_filter.blockSignals(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        if plan.audit_reapply:
            self.progress_label.setText("Audit scan complete")
        elif plan.official_version_already_applied:
            self.progress_label.setText("Already applied")
        else:
            self.progress_label.setText("Scan complete")
        self._populate_plan()
        if not self.output_edit.text().strip():
            current = Path(plan.current_root)
            version = plan.new_version.strip().replace("/", "-").replace("\\", "-")
            suffix = f" {version}" if version and version != "new version" else " Updated"
            self.output_edit.setText(str(current.with_name(current.name + suffix)))

    def _on_scan_failed(self, message: str):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress_label.setText("Scan failed")
        if "cancelled" not in message.lower():
            QMessageBox.critical(self, "Version Update scan failed", message)
        else:
            self.summary_label.setText(message)

    def _release_scan_worker(self):
        self.scan_btn.setEnabled(True)
        self.cancel_scan_btn.setEnabled(False)
        worker = self._scan_worker
        self._scan_worker = None
        if worker:
            worker.deleteLater()

    @staticmethod
    def _action_label(action: UpdateAction) -> str:
        return {
            UpdateAction.KEEP: "Keep",
            UpdateAction.PRESERVE_TRANSLATED: "Preserve translation",
            UpdateAction.USE_NEW: "Use new",
            UpdateAction.ADD_NEW: "Add new",
            UpdateAction.PRESERVE_ADDED: "Preserve added",
            UpdateAction.DELETE: "Delete",
            UpdateAction.MERGE_TEXT: "Merge text",
            UpdateAction.MERGE_SEMANTIC: "Merge game data",
            UpdateAction.PROTECT_CURRENT: "Protect local",
            UpdateAction.CONFLICT: "Review local change",
        }[action]

    def _populate_plan(self):
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        self._items.clear()
        for index, decision in enumerate(self._plan.decisions):
            status = self._status_text(decision)
            item = QTreeWidgetItem(
                [
                    self._action_label(decision.action),
                    decision.relative_path,
                    decision.kind.value,
                    status,
                ]
            )
            item.setData(0, Qt.UserRole, index)
            self._set_item_appearance(item, decision)
            self.tree.addTopLevelItem(item)
            self._items[index] = item
        self.tree.setSortingEnabled(True)
        for column in (0, 2, 3):
            self.tree.resizeColumnToContents(column)
        self.apply_recommended_btn.setEnabled(True)
        self._apply_filters()
        self._refresh_summary()

    @staticmethod
    def _status_text(decision) -> str:
        if decision.action == UpdateAction.CONFLICT:
            if decision.blocking:
                status = "Choice required"
            elif decision.resolution == ConflictResolution.USE_PROPOSED:
                status = (
                    "Recommended: merge both"
                    if decision.resolution_is_automatic
                    else "Merge both"
                )
            elif decision.resolution == ConflictResolution.USE_NEW:
                status = (
                    "Review: new wins"
                    if decision.resolution_is_automatic
                    else "New wins"
                )
            elif decision.resolution == ConflictResolution.KEEP_CURRENT:
                status = "Current wins"
            elif decision.resolution == ConflictResolution.USE_MERGED_FILE:
                status = "Manual merged file"
            else:
                status = "Choice required"
        elif decision.needs_translation:
            status = "Needs translation"
        elif decision.needs_review:
            status = "Merged: review"
        else:
            status = "Ready"
        if decision.recovery_status == RecoveryStatus.DEFINITE_REVERT:
            return f"Definite revert · {status}"
        if decision.recovery_status == RecoveryStatus.POSSIBLE_REVERT:
            return f"Possible revert/local edit · {status}"
        if decision.recovery_status == RecoveryStatus.ALREADY_PRESENT:
            return f"Official change present · {status}"
        return status

    @staticmethod
    def _set_item_appearance(item, decision):
        item.setForeground(0, QBrush())
        if decision.translation_at_risk:
            item.setForeground(0, QBrush(QColor("#f0ad4e")))
        elif decision.action == UpdateAction.CONFLICT:
            item.setForeground(0, QBrush(QColor("#8fd19e")))
        elif decision.needs_translation:
            item.setForeground(0, QBrush(QColor("#d7ba7d")))
        elif decision.action in {UpdateAction.ADD_NEW, UpdateAction.USE_NEW}:
            item.setForeground(0, QBrush(QColor("#9cdcfe")))

    def _apply_filters(self, *_args):
        if not self._plan:
            return
        category = self.review_filter.currentData() or "review"
        query = self.review_search.text().strip().casefold()
        for index, item in self._items.items():
            decision = self._plan.decisions[index]
            matches_category = {
                "review": decision.needs_review,
                "recovery": decision.recovery_status in {
                    RecoveryStatus.DEFINITE_REVERT,
                    RecoveryStatus.POSSIBLE_REVERT,
                },
                "risk": decision.translation_at_risk,
                "merged": decision.action in {
                    UpdateAction.MERGE_TEXT,
                    UpdateAction.MERGE_SEMANTIC,
                }
                or decision.resolution == ConflictResolution.USE_PROPOSED,
                "upstream": decision.action in {
                    UpdateAction.ADD_NEW,
                    UpdateAction.USE_NEW,
                    UpdateAction.DELETE,
                }
                or decision.resolution == ConflictResolution.USE_NEW,
                "all": True,
            }.get(category, True)
            item.setHidden(not (matches_category and query in decision.relative_path.casefold()))
        self._refresh_summary()

    def _refresh_summary(self):
        if not self._plan:
            return
        summary = self._plan.summary()
        already_applied = (
            self._plan.official_version_already_applied
            and not self._plan.audit_reapply
        )
        ready = not self._plan.blocking_conflicts and not already_applied
        visible = sum(not item.isHidden() for item in self._items.values())
        if already_applied:
            unavailable = (
                f" Automatic recovery was unavailable: {self._plan.recovery_error}"
                if self._plan.recovery_error
                else ""
            )
            self.summary_label.setText(
                "This official build exactly matches the saved baseline, so it was already "
                "applied and there is no newer update to install."
                + unavailable
            )
        else:
            mode = (
                "Recovery audit · This official build was already applied; the prior update "
                "was reconstructed for review. · "
                f"{summary['definite_reverts']:,} definite full-file "
                f"{_plural(summary['definite_reverts'], 'revert')} · "
                f"{summary['possible_reverts']:,} possible "
                f"{_plural(summary['possible_reverts'], 'revert')} or later local edits · "
                if self._plan.audit_reapply
                else ""
            )
            self.summary_label.setText(
                f"{mode}Old source: {self._plan.old_source_label} · "
                f"Profile: {self._plan.profile_id} · {len(self._plan.decisions):,} files · "
                f"showing {visible:,} · "
                f"{summary['add_new']:,} new · {summary['use_new']:,} upstream changes · "
                f"{summary['preserve_translated']:,} translated files preserved · "
                f"{summary['automatic_resolutions']:,} recommended choices · "
                f"{summary['translation_at_risk']:,} local files at risk · "
                f"{summary['needs_translation']:,} text segments need translation · "
                f"{summary['blocking_conflicts']:,} unresolved conflicts"
            )
        self.apply_btn.setEnabled(
            ready and not (self._apply_worker and self._apply_worker.isRunning())
        )
        self.custom_apply_btn.setEnabled(
            ready and not (self._apply_worker and self._apply_worker.isRunning())
        )

    def _decision_for_item(self, item):
        if not item or not self._plan:
            return None
        index = item.data(0, Qt.UserRole)
        if not isinstance(index, int) or index >= len(self._plan.decisions):
            return None
        return self._plan.decisions[index]

    def _show_selected(self, current, _previous):
        decision = self._decision_for_item(current)
        self._set_resolution_buttons(decision)
        if not decision:
            self.details.clear()
            self.technical_details.clear()
            self.technical_toggle.setChecked(False)
            self.technical_toggle.setVisible(False)
            return
        summary, technical = _format_decision_details(decision)
        self.details.setPlainText(summary)
        self.technical_details.setPlainText(technical)
        self.technical_toggle.setChecked(False)
        self.technical_toggle.setVisible(True)
        self.technical_details.setVisible(False)

    def _toggle_technical_details(self, checked: bool):
        self.technical_details.setVisible(checked)
        self.technical_toggle.setText(
            "Hide technical merge log" if checked else "Show technical merge log"
        )

    def _set_resolution_buttons(self, decision):
        conflicts = self._selected_conflict_items()
        count = len(conflicts)
        self.resolution_label.setText(
            f"{count} selected review item{'s' if count != 1 else ''}. "
            "These buttons override the recommended result."
            if count
            else "Select one or more review items. Recommended choices are already applied."
        )
        self.use_new_btn.setEnabled(bool(conflicts))
        self.keep_current_btn.setEnabled(bool(conflicts))
        self.provide_merge_btn.setEnabled(count == 1)
        self.use_proposed_btn.setEnabled(
            bool(conflicts)
            and all(item[1].generated_content is not None for item in conflicts)
        )

    def _selection_changed(self):
        self._set_resolution_buttons(self._decision_for_item(self.tree.currentItem()))

    def _selected_conflict_items(self):
        selected = self.tree.selectedItems()
        if not selected and self.tree.currentItem():
            selected = [self.tree.currentItem()]
        result = []
        for item in selected:
            decision = self._decision_for_item(item)
            if decision and decision.action == UpdateAction.CONFLICT:
                result.append((item, decision))
        return result

    def _resolve_selected(self, resolution: ConflictResolution):
        changed = False
        for item, decision in self._selected_conflict_items():
            if resolution == ConflictResolution.USE_PROPOSED and decision.generated_content is None:
                continue
            decision.resolution = resolution
            decision.resolution_is_automatic = False
            decision.merged_file = None
            item.setText(3, self._status_text(decision))
            self._set_item_appearance(item, decision)
            changed = True
        if not changed:
            return
        self._apply_filters()
        self._show_selected(self.tree.currentItem(), None)
        self._refresh_summary()

    def _apply_recommended_to_all(self):
        if not self._plan:
            return
        for index, decision in enumerate(self._plan.decisions):
            if decision.action != UpdateAction.CONFLICT or not decision.recommended_resolution:
                continue
            decision.resolution = decision.recommended_resolution
            decision.resolution_is_automatic = True
            decision.merged_file = None
            item = self._items[index]
            item.setText(3, self._status_text(decision))
            self._set_item_appearance(item, decision)
        self._apply_filters()
        self._show_selected(self.tree.currentItem(), None)
        self._refresh_summary()

    def _apply_recommended(self):
        """Restore the upstream-first recommendations and create the staged copy."""
        self._apply_recommended_to_all()
        self._apply(recommended=True)

    def _provide_merged_file(self):
        item = self.tree.currentItem()
        decision = self._decision_for_item(item)
        if not decision or decision.action != UpdateAction.CONFLICT:
            return
        start = (
            str(Path(decision.current.source_path).parent)
            if decision.current and decision.current.source_path
            else ""
        )
        filename, _ = QFileDialog.getOpenFileName(self, "Select reviewed merged file", start)
        if not filename:
            return
        decision.merged_file = Path(filename)
        decision.resolution = ConflictResolution.USE_MERGED_FILE
        decision.resolution_is_automatic = False
        item.setText(3, self._status_text(decision))
        self._set_item_appearance(item, decision)
        self._apply_filters()
        self._show_selected(item, None)
        self._refresh_summary()

    def _apply(self, _checked=False, *, recommended=False):
        if not self._plan or self._plan.blocking_conflicts:
            return
        in_place = self.in_place_mode_radio.isChecked()
        recovery = self._plan.audit_reapply
        output = str(self._plan.current_root) if in_place else self.output_edit.text().strip()
        if not in_place and not output:
            QMessageBox.warning(self, "Missing output", "Select a new output folder.")
            return
        reply = QMessageBox.question(
            self,
            (
                "Reapply recovered changes"
                if recovery
                else "Update translated game folder"
                if in_place
                else ("Create recommended update" if recommended else "Create reviewed update")
            ),
            (
                f"Replace the translated game folder after staging succeeds:\n{output}\n\n"
                if in_place
                else f"Create an updated copy at:\n{output}\n\n"
            )
            + (
                f"Reapply recovered changes from {self._plan.old_version} → "
                f"{self._plan.new_version}?\n"
                if recovery
                else f"Update {self._plan.old_version} → {self._plan.new_version}?\n"
            )
            + (
                "This official version was previously applied. The recovery audit reconstructed "
                "its historical update; no files change unless you confirm this reapply.\n"
                if recovery
                else ""
            )
            + (
                "Recommended mode will apply every official change and preserve only local "
                "changes that can be merged safely.\n"
                if recommended
                else "Your review overrides will be used.\n"
            )
            + f"{self._plan.summary()['translation_at_risk']} file(s) will use the new "
            "official version instead of a differing local file; these can be reconciled "
            "in the output afterward.\n\n"
            + (
                "The previous translated folder will be kept as a sibling rollback backup. "
                "The official source folders will not be modified."
                if in_place
                else "The three input folders will not be modified."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.apply_btn.setEnabled(False)
        self.custom_apply_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress_label.setText(
            "Reapplying recovered changes…"
            if recovery
            else "Staging in-place update…"
            if in_place
            else "Creating updated copy…"
        )
        worker = _ApplyWorker(self._plan, output, in_place=in_place)
        worker.progress.connect(self._on_apply_progress)
        worker.done.connect(self._on_apply_done)
        worker.failed.connect(self._on_apply_failed)
        worker.finished.connect(self._release_apply_worker)
        self._apply_worker = worker
        worker.start()

    def _on_apply_progress(self, current: int, total: int, detail: str):
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(current)
        self.progress_label.setText(f"Applying: {detail}")

    def _on_apply_done(self, result):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress_label.setText(
            "Recovery reapply complete"
            if self._plan.audit_reapply
            else "Version update complete"
        )
        self.finish_label.setStyleSheet("color:#6a9955;font-weight:bold;")
        self.finish_label.setText(
            f"Updated from {self._plan.old_version} to {self._plan.new_version}: "
            f"{result.files_written:,} files written, {result.files_deleted:,} deleted, "
            f"{result.preserved_translations:,} translated segments preserved, and "
            f"{result.needs_translation:,} segments ready for translation.\n"
            f"Output: {result.output_root}\n"
            + (f"Rollback backup: {result.backup_root}\n" if result.backup_root else "")
            + f"Report: {result.report_path}\n"
            + "Before release, launch the output and smoke-test the affected maps and plugins."
        )
        self._last_output = Path(result.output_root)
        self.continue_workflow_btn.setEnabled(True)
        self.open_images_btn.setEnabled(True)

    def _on_apply_failed(self, message: str):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress_label.setText("Update failed")
        QMessageBox.critical(self, "Version update failed", message)

    def _release_apply_worker(self):
        self.scan_btn.setEnabled(True)
        worker = self._apply_worker
        self._apply_worker = None
        if worker:
            worker.deleteLater()
        self._refresh_summary()

    def _continue_in_workflow(self):
        if self._last_output is None:
            return
        host = self.window()
        workflow = getattr(host, "workflow_tab", None)
        if workflow is None:
            return
        engine_combo = getattr(host, "workflow_engine_combo", None)
        if engine_combo is not None:
            engine_combo.setCurrentIndex(0)
        workflow.folder_edit.setText(str(self._last_output))
        workflow._detect_folder()
        switch = getattr(host, "switch_page", None)
        if callable(switch):
            switch(getattr(host, "PAGE_WORKFLOW", 1))

    def _open_output_images(self):
        if self._last_output is None:
            return
        host = self.window()
        manager = getattr(host, "image_manager_tab", None)
        if manager is None:
            return
        manager.folder_edit.setText(str(self._last_output))
        manager._load_project()
        switch = getattr(host, "switch_page", None)
        if callable(switch):
            switch(getattr(host, "PAGE_IMAGES", 2))
