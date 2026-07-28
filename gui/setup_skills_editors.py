"""Shared Vocab / Quirks / Game skills editors for Workflow Setup steps."""

from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from util.skills import (
    custom_skill_path_for_game,
    game_skill_path_for_game,
    list_custom_skill_paths,
    migrate_game_skill_text,
    quirks_path_for_game,
    sanitize_custom_skill_stem,
)
from util.vocab import read_game_vocab, write_game_vocab
from gui.theme import Geometry, Spacing


class _PlainPasteTextEdit(QTextEdit):
    """QTextEdit that always pastes as plain text."""

    def insertFromMimeData(self, source):  # noqa: N802
        self.insertPlainText(source.text())


def _make_btn(text: str, color: str = "#0e639c") -> QPushButton:
    """Match the shared semantic workflow button hierarchy."""
    from gui.theme import COLORS
    from gui.workflow_components import make_workflow_button

    normalized = color.lower().strip()
    if normalized in {"#7a3a3a", "#8b0000", "#cc2222", "#cc4444"}:
        variant = "danger"
    elif normalized in {
        "#45454a", "#555", "#5a5a60", "#444", "#444444",
        COLORS.border.lower(), COLORS.border_strong.lower(), COLORS.surface_1.lower(),
    }:
        variant = "secondary"
    else:
        variant = "primary"
    btn = make_workflow_button(text, variant=variant)
    _icon_color = {
        "primary": "#ffffff",
        "danger": COLORS.danger,
        "secondary": COLORS.text_secondary,
    }[variant]
    from gui import qt_icons

    qt_icons.apply_button_icon(btn, text, color=_icon_color)
    if not btn.icon().isNull():
        btn.setIconSize(QSize(16, 16))
    return btn


class SetupSkillsEditors(QWidget):
    """Tabbed Vocab / Quirks / Game skills editors for Workflow Setup.

    Parameters
    ----------
    game_root_fn:
        Callable returning the current game root path (may be empty).
    log_fn:
        Callable used for status / error messages.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        game_root_fn: Callable[[], str],
        log_fn: Callable[[str], None],
    ):
        super().__init__(parent)
        self._game_root_fn = game_root_fn
        self._log = log_fn
        self._custom_skill_editors: dict[str, QTextEdit] = {}
        self.vocab_editor: QTextEdit | None = None
        self.quirks_editor: QTextEdit | None = None
        self.game_skill_editor: QTextEdit | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        editors = QTabWidget()
        editors.setObjectName("setupEditors")
        editors.setDocumentMode(False)
        tab_bar = editors.tabBar()
        tab_bar.setExpanding(False)
        tab_bar.setMinimumHeight(34)
        tab_bar.setStyleSheet(
            "QTabBar::tab{background:#333337;color:#c0c0c0;min-width:90px;min-height:28px;"
            "padding:6px 16px;border:1px solid #45454a;border-bottom:none;"
            "margin-right:3px;font-size:12px;font-weight:bold;}"
            "QTabBar::tab:selected{background:#1e1e1e;color:#f2f2f2;"
            "border-top:2px solid #f2f2f2;}"
            "QTabBar::tab:hover{color:#ffffff;}"
        )
        editors.setStyleSheet(
            "QTabWidget::pane{border:1px solid #45454a;background:#1e1e1e;}"
        )

        editors.addTab(
            self._editor_page(
                "data/vocab.txt  (game section)",
                "Paste the glossary code block. Format: Japanese (English) - notes",
                self._save_vocab,
                self._reload_vocab,
                "vocab_editor",
            ),
            "Vocab",
        )
        editors.addTab(
            self._editor_page(
                "<game>/skills/quirks.md",
                "Paste the translation_quirks block. Merged onto the system prompt at translate time.",
                self._save_quirks,
                self._reload_quirks,
                "quirks_editor",
            ),
            "Quirks",
        )

        game_skills_page = QWidget()
        gs_layout = QVBoxLayout(game_skills_page)
        gs_layout.setContentsMargins(0, 0, 0, 0)
        gs_layout.setSpacing(0)

        self._game_skills_bar = QTabBar()
        self._game_skills_bar.setDocumentMode(True)
        self._game_skills_bar.setExpanding(False)
        self._game_skills_bar.setDrawBase(False)
        self._game_skills_bar.setMinimumHeight(30)
        self._game_skills_bar.setStyleSheet(
            "QTabBar::tab{background:#2d2d30;color:#a6a6a6;padding:6px 12px;"
            "border:1px solid #45454a;border-bottom:none;margin-right:2px;}"
            "QTabBar::tab:selected{background:#1e1e1e;color:#f2f2f2;}"
            "QTabBar::tab:hover{color:#ffffff;}"
        )
        self._game_skills_stack = QStackedWidget()
        self._game_skills_stack.setStyleSheet("background:#1e1e1e;")
        self._game_skills_bar.currentChanged.connect(
            self._game_skills_stack.setCurrentIndex
        )

        strip = QWidget()
        strip.setStyleSheet("background-color:#252526;")
        strip_l = QHBoxLayout(strip)
        strip_l.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.MD, 0)
        strip_l.setSpacing(Spacing.SM)
        strip_l.addWidget(self._game_skills_bar, 0, Qt.AlignBottom)

        add_btn = QPushButton("+ Add custom")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setMinimumHeight(Geometry.CONTROL)
        add_btn.setToolTip(
            "Create a custom skills/*.md overlay.\n"
            "Merged into the translation system prompt - can hurt quality."
        )
        add_btn.setStyleSheet(
            "QPushButton{background-color:#2d2d30;color:#f2f2f2;"
            "border:1px solid #45454a;border-bottom:none;"
            "border-top-left-radius:3px;border-top-right-radius:3px;"
            "padding:0 12px;font-size:12px;font-weight:bold;}"
            "QPushButton:hover{background-color:#45454a;color:#ffffff;"
            "border-color:#f2f2f2;}"
            "QPushButton:pressed{background-color:#1e1e1e;}"
        )
        add_btn.clicked.connect(self._add_custom_skill)
        strip_l.addWidget(add_btn, 0, Qt.AlignBottom)
        strip_l.addStretch(1)
        gs_layout.addWidget(strip)
        gs_layout.addWidget(self._game_skills_stack, 1)

        self._add_game_skill_page(
            "game",
            self._editor_page(
                "<game>/skills/game.md",
                "Paste the game_skill Translation Frame. Merged into the translation "
                "system prompt (before quirks) when this game folder is selected.",
                self._save_game_skill,
                self._reload_game_skill,
                "game_skill_editor",
            ),
        )
        editors.addTab(game_skills_page, "Game skills")
        root.addWidget(editors, 1)

    def _editor_page(
        self,
        path_hint: str,
        tip: str,
        save_slot,
        reload_slot,
        attr: str,
    ) -> QWidget:
        page = QWidget()
        vl = QVBoxLayout(page)
        vl.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        vl.setSpacing(Spacing.SM)
        tip_lbl = QLabel(tip)
        tip_lbl.setWordWrap(True)
        tip_lbl.setStyleSheet("color:#a6a6a6;font-size:12px;")
        vl.addWidget(tip_lbl)
        path_lbl = QLabel(path_hint)
        path_lbl.setStyleSheet(
            "color:#75beff;font-size:11px;font-family:Consolas,monospace;"
        )
        vl.addWidget(path_lbl)
        ed = _PlainPasteTextEdit()
        ed.setMinimumHeight(160)
        ed.setFont(QFont("Consolas", 9))
        ed.setStyleSheet(
            "QTextEdit{background-color:#1e1e1e;color:#c8c8c8;"
            "border:none;padding:8px;"
            "selection-background-color:#264f78;}"
        )
        setattr(self, attr, ed)
        vl.addWidget(ed, 1)
        row = QHBoxLayout()
        row.setSpacing(Spacing.SM)
        save_btn = _make_btn("💾  Save", "#0e639c")
        save_btn.setFixedWidth(128)
        save_btn.clicked.connect(save_slot)
        row.addWidget(save_btn)
        reload_btn = _make_btn("↺  Reload", "#555")
        reload_btn.setFixedWidth(128)
        reload_btn.clicked.connect(reload_slot)
        row.addWidget(reload_btn)
        row.addStretch()
        vl.addLayout(row)
        return page

    def reload_all(self) -> None:
        """Reload vocab, quirks, game skill, and custom skill tabs from disk."""
        self._reload_vocab()
        self._reload_quirks()
        self._reload_game_skill()
        self._reload_custom_skills()

    def _game_root(self) -> str:
        return (self._game_root_fn() or "").strip()

    def _game_root_or_warn(self) -> str | None:
        root = self._game_root()
        if not root:
            self._log("⚠  Select a game folder in Step 0 first.")
            return None
        return root

    def _reload_vocab(self) -> None:
        if self.vocab_editor is None:
            return
        try:
            self.vocab_editor.setPlainText(read_game_vocab())
        except Exception as exc:
            self._log(f"❌ Could not load vocab.txt: {exc}")

    def _save_vocab(self) -> None:
        if self.vocab_editor is None:
            return
        try:
            write_game_vocab(self.vocab_editor.toPlainText())
            self._log("✅ vocab.txt saved (base terms from vocab_base.txt appended).")
        except Exception as exc:
            self._log(f"❌ Could not save vocab.txt: {exc}")

    def _reload_quirks(self) -> None:
        if self.quirks_editor is None:
            return
        path = quirks_path_for_game(self._game_root())
        if not path or not path.is_file():
            self.quirks_editor.setPlainText("")
            return
        try:
            self.quirks_editor.setPlainText(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._log(f"❌ Could not load skills/quirks.md: {exc}")

    def _save_quirks(self) -> None:
        root = self._game_root_or_warn()
        if not root or self.quirks_editor is None:
            return
        path = quirks_path_for_game(root)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                self.quirks_editor.toPlainText().rstrip() + "\n", encoding="utf-8"
            )
            self._log(f"✅ Saved {path}")
        except Exception as exc:
            self._log(f"❌ Could not save skills/quirks.md: {exc}")

    def _reload_game_skill(self) -> None:
        if self.game_skill_editor is None:
            return
        path = game_skill_path_for_game(self._game_root())
        if not path or not path.is_file():
            self.game_skill_editor.setPlainText("")
            return
        try:
            raw = path.read_text(encoding="utf-8")
            fixed = migrate_game_skill_text(raw)
            self.game_skill_editor.setPlainText(fixed)
            if fixed != raw:
                path.write_text(fixed.rstrip() + "\n", encoding="utf-8")
                self._log(
                    f"↺  Updated legacy sections in {path.name} for API use"
                )
        except Exception as exc:
            self._log(f"❌ Could not load game skill: {exc}")

    def _save_game_skill(self) -> None:
        root = self._game_root_or_warn()
        if not root or self.game_skill_editor is None:
            return
        path = game_skill_path_for_game(root)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = migrate_game_skill_text(self.game_skill_editor.toPlainText())
            self.game_skill_editor.setPlainText(text)
            path.write_text(text.rstrip() + "\n", encoding="utf-8")
            self._log(f"✅ Saved {path}")
        except Exception as exc:
            self._log(f"❌ Could not save game skill: {exc}")

    def _add_game_skill_page(self, title: str, page: QWidget) -> int:
        idx = self._game_skills_stack.addWidget(page)
        self._game_skills_bar.addTab(title)
        return idx

    def _select_game_skill_tab(self, title: str) -> None:
        for i in range(self._game_skills_bar.count()):
            if self._game_skills_bar.tabText(i) == title:
                self._game_skills_bar.setCurrentIndex(i)
                return

    def _custom_skill_editor_page(self, stem: str) -> QWidget:
        page = QWidget()
        vl = QVBoxLayout(page)
        vl.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        vl.setSpacing(Spacing.SM)

        tip = QLabel(
            "Custom skill - merged into the translation system prompt. "
            "Extra or conflicting rules can hurt quality."
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#c9a227;font-size:12px;")
        vl.addWidget(tip)

        path_lbl = QLabel(f"<game>/skills/{stem}.md")
        path_lbl.setStyleSheet(
            "color:#75beff;font-size:11px;font-family:Consolas,monospace;"
        )
        vl.addWidget(path_lbl)

        ed = _PlainPasteTextEdit()
        ed.setMinimumHeight(160)
        ed.setFont(QFont("Consolas", 9))
        ed.setStyleSheet(
            "QTextEdit{background-color:#1e1e1e;color:#c8c8c8;"
            "border:none;padding:8px;"
            "selection-background-color:#264f78;}"
        )
        self._custom_skill_editors[stem] = ed
        vl.addWidget(ed, 1)

        row = QHBoxLayout()
        row.setSpacing(Spacing.SM)
        save_btn = _make_btn("💾  Save", "#0e639c")
        save_btn.setFixedWidth(128)
        save_btn.clicked.connect(lambda _=False, s=stem: self._save_custom_skill(s))
        row.addWidget(save_btn)

        reload_btn = _make_btn("↺  Reload", "#555")
        reload_btn.setFixedWidth(128)
        reload_btn.clicked.connect(
            lambda _=False, s=stem: self._reload_one_custom_skill(s)
        )
        row.addWidget(reload_btn)

        delete_btn = _make_btn("🗑  Delete", "#8b0000")
        delete_btn.setFixedWidth(128)
        delete_btn.setToolTip("Delete this custom skill file from the game folder")
        delete_btn.clicked.connect(lambda _=False, s=stem: self._delete_custom_skill(s))
        row.addWidget(delete_btn)
        row.addStretch()
        vl.addLayout(row)
        return page

    def _reload_custom_skills(self) -> None:
        bar = getattr(self, "_game_skills_bar", None)
        stack = getattr(self, "_game_skills_stack", None)
        if bar is None or stack is None:
            return

        while bar.count() > 1:
            bar.removeTab(1)
        while stack.count() > 1:
            w = stack.widget(1)
            stack.removeWidget(w)
            if w is not None:
                w.deleteLater()
        self._custom_skill_editors = {}

        for path in list_custom_skill_paths(self._game_root()):
            stem = path.stem
            page = self._custom_skill_editor_page(stem)
            self._add_game_skill_page(stem, page)
            try:
                self._custom_skill_editors[stem].setPlainText(
                    path.read_text(encoding="utf-8")
                )
            except Exception as exc:
                self._log(f"❌ Could not load skills/{stem}.md: {exc}")

    def _reload_one_custom_skill(self, stem: str) -> None:
        path = custom_skill_path_for_game(self._game_root(), stem)
        ed = self._custom_skill_editors.get(stem)
        if ed is None:
            return
        if not path or not path.is_file():
            ed.setPlainText("")
            return
        try:
            ed.setPlainText(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._log(f"❌ Could not load skills/{stem}.md: {exc}")

    def _save_custom_skill(self, stem: str) -> None:
        root = self._game_root_or_warn()
        if not root:
            return
        path = custom_skill_path_for_game(root, stem)
        ed = self._custom_skill_editors.get(stem)
        if path is None or ed is None:
            self._log("❌ Invalid custom skill.")
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(ed.toPlainText().rstrip() + "\n", encoding="utf-8")
            self._log(f"✅ Saved {path}")
        except Exception as exc:
            self._log(f"❌ Could not save skills/{stem}.md: {exc}")

    def _add_custom_skill(self) -> None:
        root = self._game_root_or_warn()
        if not root:
            return

        warn = QMessageBox(self)
        warn.setIcon(QMessageBox.Warning)
        warn.setWindowTitle("Custom skill - quality warning")
        warn.setTextFormat(Qt.RichText)
        warn.setText(
            "<b>Custom skills are merged into the translation system prompt.</b><br><br>"
            "Extra or poorly written skills can <b>distract the model and hurt "
            "translation quality</b> (conflicting rules, prompt bloat, diluted quirks).<br><br>"
            "Prefer <code>quirks.md</code> for voice rules and <code>game.md</code> "
            "for the Translation Frame. Add a custom skill only if you need a rare, tightly scoped "
            "overlay - <b>at your own risk</b>."
        )
        warn.setStandardButtons(QMessageBox.Cancel | QMessageBox.Ok)
        warn.button(QMessageBox.Ok).setText("I understand - continue")
        warn.setStyleSheet(
            "QMessageBox{background-color:#252526;}"
            "QLabel{color:#c8c8c8;font-size:13px;min-width:420px;}"
        )
        if warn.exec_() != QMessageBox.Ok:
            return

        name, ok = QInputDialog.getText(
            self,
            "New custom skill",
            "Skill file name (letters, numbers, ._- ; saved as <game>/skills/<name>.md):",
        )
        if not ok:
            return
        stem = sanitize_custom_skill_stem(name)
        if not stem:
            QMessageBox.warning(
                self,
                "Invalid name",
                "Use a short name like battle-log or honorifics_extra.\n"
                "Reserved: quirks, game, translation.",
            )
            return
        if stem in self._custom_skill_editors:
            QMessageBox.information(
                self, "Already exists", f"Custom skill '{stem}' is already open."
            )
            self._select_game_skill_tab(stem)
            return

        path = custom_skill_path_for_game(root, stem)
        if path is None:
            return
        if path.is_file():
            self._reload_custom_skills()
            self._select_game_skill_tab(stem)
            return

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"# {stem}\n\n"
                "# Keep this short and specific. Conflicting rules hurt quality.\n",
                encoding="utf-8",
            )
        except Exception as exc:
            self._log(f"❌ Could not create skills/{stem}.md: {exc}")
            return

        page = self._custom_skill_editor_page(stem)
        idx = self._add_game_skill_page(stem, page)
        self._game_skills_bar.setCurrentIndex(idx)
        self._reload_one_custom_skill(stem)
        self._log(f"✅ Created custom skill {path}")

    def _delete_custom_skill(self, stem: str) -> None:
        root = self._game_root_or_warn()
        if not root:
            return
        path = custom_skill_path_for_game(root, stem)
        reply = QMessageBox.question(
            self,
            "Delete custom skill",
            f"Delete skills/{stem}.md from the game folder?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            if path and path.is_file():
                path.unlink()
            self._log(f"🗑  Deleted {path}")
        except Exception as exc:
            self._log(f"❌ Could not delete skills/{stem}.md: {exc}")
            return
        self._reload_custom_skills()
