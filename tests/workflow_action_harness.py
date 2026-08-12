"""Reusable, side-effect-safe fixtures for RPG Maker workflow action tests.

The visual capture harness deliberately never invokes workflow actions.  This
module provides the complementary behavioral harness: controls can be clicked
normally while virtual action slots record their routing, and real handlers can
be exercised inside a disposable working directory with fake Qt workers.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication, QPushButton

from gui.setup_skills_editors import SetupSkillsEditors
from gui.workflow_tab import WorkflowTab


@dataclass(frozen=True)
class ActionCall:
    """One virtual action reached through a real Qt signal connection."""

    name: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


class Signal:
    """Small Qt-signal substitute used by workers in handler contract tests."""

    def __init__(self) -> None:
        self.callbacks: list[Callable[..., Any]] = []

    def connect(self, callback: Callable[..., Any]) -> None:
        self.callbacks.append(callback)

    def emit(self, *args: Any) -> None:
        for callback in tuple(self.callbacks):
            callback(*args)


class FakeWorker:
    """Records worker construction/start without launching a thread or process."""

    instances: list["FakeWorker"] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        self.started = False
        self.deleted = False
        self.running = False
        self.log = Signal()
        self.done = Signal()
        self.error = Signal()
        self.failed = Signal()
        self.finished = Signal()
        type(self).instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.instances.clear()

    def start(self) -> None:
        self.started = True

    def isRunning(self) -> bool:  # noqa: N802 - mirrors QThread
        return self.running

    def deleteLater(self) -> None:  # noqa: N802 - mirrors QObject
        self.deleted = True


class SetupEditorsActionProbe(SetupSkillsEditors):
    """Records editor commands while retaining the production editor layout."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.actions: list[ActionCall] = []
        super().__init__(*args, **kwargs)

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.actions.append(ActionCall(name, args, kwargs))

    def _save_vocab(self, *args: Any, **kwargs: Any) -> None:
        self._record("save_vocab", *args, **kwargs)

    def _reload_vocab(self, *args: Any, **kwargs: Any) -> None:
        self._record("reload_vocab", *args, **kwargs)

    def _save_quirks(self, *args: Any, **kwargs: Any) -> None:
        self._record("save_quirks", *args, **kwargs)

    def _reload_quirks(self, *args: Any, **kwargs: Any) -> None:
        self._record("reload_quirks", *args, **kwargs)

    def _save_game_skill(self, *args: Any, **kwargs: Any) -> None:
        self._record("save_game_skill", *args, **kwargs)

    def _reload_game_skill(self, *args: Any, **kwargs: Any) -> None:
        self._record("reload_game_skill", *args, **kwargs)

    def _reload_custom_skills(self, *args: Any, **kwargs: Any) -> None:
        self._record("reload_custom_skills", *args, **kwargs)

    def _add_custom_skill(self, *args: Any, **kwargs: Any) -> None:
        self._record("add_custom_skill", *args, **kwargs)


class WorkflowActionProbe(WorkflowTab):
    """Production workflow UI whose mutating/action slots are virtual probes."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.actions: list[ActionCall] = []
        super().__init__(*args, **kwargs)

    def _record_action(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.actions.append(ActionCall(name, args, kwargs))


def _install_probe_method(name: str) -> None:
    def probe(self: WorkflowActionProbe, *args: Any, **kwargs: Any) -> None:
        self._record_action(name.removeprefix("_"), *args, **kwargs)

    probe.__name__ = name
    setattr(WorkflowActionProbe, name, probe)


# These are action endpoints connected by the production UI.  Replacing them
# in a subclass keeps all layouts and Qt signal connections genuine while
# preventing dialogs, file mutation, process launch, or host-page navigation.
for _method_name in (
    "_detect_folder",
    "_browse_folder",
    "_select_all_files",
    "_deselect_all_files",
    "_select_core_only",
    "_import_files",
    "_run_dazedformat",
    "_browse_plugins_js",
    "_run_prettier",
    "_browse_gameupdate",
    "_run_gameupdate",
    "_run_all_preprocess",
    "_clear_translated",
    "_apply_speaker_flags",
    "_run_parse_speakers",
    "_copy_project_setup_prompt",
    "_reload_setup_guidance",
    "_apply_wrap_config",
    "_run_phase",
    "_copy_plugin_prompt",
    "_apply_var_range",
    "_schedule_p2_config_apply",
    "_select_rewrap_files",
    "_refresh_rewrap_files",
    "_load_rewrap_widths",
    "_run_rewrap",
    "_copy_localization_investigation_prompt",
    "_reload_investigation_guidance",
    "_prepare_translation_qa",
    "_copy_qa_final_rebuild_handoff",
    "_create_public_release",
    "_copy_plugins_js_translate_prompt",
    "_export_active_files",
    "_export_to_game",
    "_refresh_image_workflow_status",
    "_open_image_manager",
    "_on_tli_editor_combo_changed",
    "_detect_tli_editors",
    "_browse_tli_editor",
    "_save_playtest_settings",
    "_apply_playtest_settings",
    "_install_tl_inspector",
    "_uninstall_tl_inspector",
    "_install_forge",
    "_uninstall_forge",
    "_install_both_playtest",
    "_refresh_playtest_status",
):
    _install_probe_method(_method_name)


class WorkflowHarness:
    """Own a disposable cwd, isolated settings, and one workflow instance."""

    def __init__(self, *, probe: bool = False, parent=None) -> None:
        self.app = QApplication.instance() or QApplication([])
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.old_cwd = Path.cwd()
        os.chdir(self.root)
        (self.root / "files").mkdir()
        (self.root / "translated").mkdir()
        self.settings = QSettings(
            str(self.root / "workflow.ini"), QSettings.IniFormat
        )
        workflow_type = WorkflowActionProbe if probe else WorkflowTab
        patches = [
            patch("gui.workflow_tab.QSettings", return_value=self.settings),
            patch("gui.workflow_tab.default_translation_mode", return_value="Translate"),
            patch("util.translation._load_litellm_pricing", return_value=None),
        ]
        if probe:
            patches.append(
                patch(
                    "gui.workflow_tab.SetupSkillsEditors",
                    SetupEditorsActionProbe,
                )
            )
        for active_patch in patches:
            active_patch.start()
        try:
            self.workflow = workflow_type(parent)
        finally:
            for active_patch in reversed(patches):
                active_patch.stop()
        self.workflow._detected_on_show = True
        self.workflow.resize(1440, 900)
        self.workflow.show()
        self.app.processEvents()
        if probe:
            self.clear_actions()

    def close(self) -> None:
        self.workflow.close()
        self.workflow.deleteLater()
        self.app.processEvents()
        os.chdir(self.old_cwd)
        self._temp.cleanup()

    def clear_actions(self) -> None:
        if hasattr(self.workflow, "actions"):
            self.workflow.actions.clear()
        editors = getattr(self.workflow, "setup_editors", None)
        if hasattr(editors, "actions"):
            editors.actions.clear()

    def button(
        self,
        step: int,
        *,
        text: str | None = None,
        tooltip: str | None = None,
        occurrence: int = 0,
    ) -> QPushButton:
        """Resolve an action by stable visible copy or tooltip within one step."""
        matches = []
        for button in self.workflow._step_tabs.widget(step).findChildren(QPushButton):
            if text is not None and button.text().strip() != text:
                continue
            if tooltip is not None and button.toolTip().strip() != tooltip:
                continue
            matches.append(button)
        if occurrence >= len(matches):
            raise AssertionError(
                f"No step {step} button matched text={text!r}, "
                f"tooltip={tooltip!r}, occurrence={occurrence}"
            )
        return matches[occurrence]

    def click(self, step: int, **locator: Any) -> QPushButton:
        button = self.button(step, **locator)
        button.setEnabled(True)
        button.click()
        self.app.processEvents()
        return button

    def make_mvmz_project(self, engine: str = "MZ") -> tuple[Path, Path]:
        """Create the smallest project recognized by the scanner and workflow."""
        game = self.root / f"Game{engine}"
        data = game / ("www/data" if engine == "MV" else "data")
        data.mkdir(parents=True)
        (data / "System.json").write_text("{}", encoding="utf-8")
        (data / "Actors.json").write_text("[]", encoding="utf-8")
        (data / "Map001.json").write_text("{}", encoding="utf-8")
        js = game / ("www/js" if engine == "MV" else "js")
        js.mkdir(parents=True)
        (js / "plugins.js").write_text("var $plugins = [];\n", encoding="utf-8")
        marker = "rpg_core.js" if engine == "MV" else "rmmz_core.js"
        (js / marker).write_text("", encoding="utf-8")
        return game, data

    def prepare_project(self, game: Path) -> None:
        """Mark a disposable project as guidance-ready without launching a scan worker."""
        root = str(game)
        self.workflow.folder_edit.setText(root)
        if not self.workflow.setup_editors.reload_all():
            raise AssertionError(f"Could not prepare disposable project: {root}")
        self.workflow._prepared_game_root = root

    def make_ace_project(self) -> tuple[Path, Path, Path]:
        game = self.root / "GameAce"
        data = game / "Data"
        ace_json = game / "ace_json"
        data.mkdir(parents=True)
        ace_json.mkdir()
        (data / "Actors.rvdata2").write_bytes(b"fixture")
        (ace_json / "Actors.json").write_text("[]", encoding="utf-8")
        return game, data, ace_json
