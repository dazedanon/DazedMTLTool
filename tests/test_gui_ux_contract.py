import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QAbstractItemView, QLabel, QPushButton, QWidget

from gui.theme import COLORS, Geometry, Spacing, contrast_ratio
from gui.ui_components import (
    UX_CONTRACT_VERSION,
    CheckableFileList,
    PageHeader,
    SectionCard,
    action_button_width_hint,
    equalize_button_widths,
    make_action_button,
    normalize_default_layout_tokens,
    refresh_equalized_button_widths,
    set_status_text,
)


ROOT = Path(__file__).resolve().parents[1]


class GUIUXContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_document_and_executable_contract_versions_match(self):
        source = (ROOT / "docs/gui-ux-contract.md").read_text(encoding="utf-8")
        self.assertIn(f"**Contract version:** {UX_CONTRACT_VERSION}", source)

    def test_spacing_and_geometry_use_the_documented_grid(self):
        self.assertEqual(
            (Spacing.XS, Spacing.SM, Spacing.MD, Spacing.LG, Spacing.XL, Spacing.XXL),
            (4, 8, 12, 16, 24, 32),
        )
        self.assertEqual(
            (Geometry.CONTROL_COMPACT, Geometry.CONTROL, Geometry.CONTROL_PROMINENT),
            (32, 36, 40),
        )
        self.assertGreaterEqual(Geometry.APP_RAIL_WIDTH, 56)

    def test_primary_and_secondary_text_contrast_on_core_surfaces(self):
        self.assertGreaterEqual(contrast_ratio(COLORS.text_primary, COLORS.canvas), 4.5)
        self.assertGreaterEqual(contrast_ratio(COLORS.text_secondary, COLORS.surface_1), 4.5)
        self.assertGreaterEqual(contrast_ratio(COLORS.on_accent, COLORS.accent), 4.5)

    def test_semantic_components_expose_stable_roles(self):
        header = PageHeader("Title", "Purpose")
        card = SectionCard("Task", "Description")
        primary = make_action_button("Apply changes", variant="primary")
        self.assertEqual(header.objectName(), "appPageHeader")
        self.assertEqual(header.title_label.objectName(), "appPageTitle")
        self.assertEqual(card.objectName(), "appSectionCard")
        self.assertEqual(primary.objectName(), "appActionButton")
        self.assertEqual(primary.property("variant"), "primary")
        self.assertGreaterEqual(primary.minimumHeight(), Geometry.CONTROL)

    def test_compact_cards_reclaim_space_without_losing_structure(self):
        card = SectionCard("Task", compact=True)
        margins = card.content_layout.contentsMargins()
        self.assertEqual(
            (margins.left(), margins.top(), margins.right(), margins.bottom()),
            (Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD),
        )
        self.assertEqual(card.content_layout.spacing(), Spacing.SM)
        self.assertEqual(card.property("density"), "compact")

    def test_declared_peer_buttons_have_identical_rendered_widths(self):
        host = QWidget()
        short = QPushButton("Open")
        long = QPushButton("Open configuration")
        short.setParent(host)
        long.setParent(host)
        width = equalize_button_widths((short, long), minimum=0)
        self.assertEqual(short.width(), width)
        self.assertEqual(long.width(), width)
        self.assertEqual(
            short.property("appEqualWidthGroup"),
            long.property("appEqualWidthGroup"),
        )
        long.setText("A much longer peer action after scaling")
        refresh_equalized_button_widths((short, long))
        self.assertEqual(short.width(), long.width())
        self.assertGreaterEqual(long.width(), long.sizeHint().width())
        self.assertGreaterEqual(long.width(), action_button_width_hint(long))

    def test_checkable_file_lists_use_extended_selection(self):
        file_list = CheckableFileList()
        self.assertEqual(
            file_list.selectionMode(), QAbstractItemView.ExtendedSelection
        )

    def test_status_contract_combines_text_and_semantic_state(self):
        status = QLabel()
        set_status_text(status, "Could not load files", "error")
        self.assertEqual(status.text(), "Could not load files")
        self.assertEqual(status.objectName(), "appStatusText")
        self.assertEqual(status.property("state"), "error")

    def test_qt_default_layout_values_are_normalized_to_the_grid(self):
        host = SectionCard()
        host.layout().setSpacing(6)
        host.layout().setContentsMargins(9, 9, 9, 9)
        normalize_default_layout_tokens((host,))
        self.assertEqual(host.layout().spacing(), Spacing.SM)
        margins = host.layout().contentsMargins()
        self.assertEqual(
            (margins.left(), margins.top(), margins.right(), margins.bottom()),
            (Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM),
        )

    def test_active_shell_and_migrated_pages_use_semantic_roles(self):
        main = (ROOT / "gui/main.py").read_text(encoding="utf-8")
        guide = (ROOT / "gui/guide_tab.py").read_text(encoding="utf-8")
        skills = (ROOT / "gui/skills_tab.py").read_text(encoding="utf-8")
        self.assertIn('sidebar.setObjectName("appSidebar")', main)
        self.assertIn("PageHeader(", guide)
        self.assertIn("PageHeader(", skills)

    def test_every_active_destination_declares_the_shared_page_hierarchy(self):
        ordinary_pages = (
            "guide_tab.py",
            "rpgmaker_image_manager.py",
            "version_update_tab.py",
            "translation_tab.py",
            "batch_tab.py",
            "skills_tab.py",
            "config_tab.py",
        )
        for filename in ordinary_pages:
            source = (ROOT / "gui" / filename).read_text(encoding="utf-8")
            self.assertIn("PageHeader(", source, filename)

        wolf = (ROOT / "gui/wolf_workflow_tab.py").read_text(encoding="utf-8")
        self.assertIn("WorkflowStepRail", wolf)
        self.assertIn("WorkflowPageHeader", wolf)
        self.assertIn("WorkflowActivityPanel", wolf)

    def test_ordinary_pages_are_not_numbered_mini_workflows(self):
        for filename in (
            "rpgmaker_image_manager.py",
            "version_update_tab.py",
            "translation_tab.py",
        ):
            source = (ROOT / "gui" / filename).read_text(encoding="utf-8")
            self.assertNotIn("TaskCard(", source, filename)
            self.assertIn("SectionCard(", source, filename)

        workflow = (ROOT / "gui" / "workflow_components.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("class TaskCard", workflow)

    def test_configuration_categories_use_shared_cards(self):
        for filename in (
            "rpgmaker_tab.py",
            "wolf_tab.py",
            "csv_tab.py",
            "srpg_tab.py",
        ):
            source = (ROOT / "gui" / filename).read_text(encoding="utf-8")
            self.assertIn("SectionCard(", source, filename)

    def test_application_capture_isolated_from_network_and_user_workspaces(self):
        source = (ROOT / "scripts/capture_app_ui.py").read_text(encoding="utf-8")
        self.assertIn("TemporaryDirectory", source)
        self.assertIn('patch.object(DazedMTLGUI, "start_background_update_check"', source)
        self.assertIn('patch("gui.config_tab.ConfigTab.fetch_models"', source)
        self.assertIn('patch("util.translation._load_litellm_pricing"', source)
        self.assertIn('patch("util.batch_history.list_local_batches"', source)
        self.assertIn('"fixture-game"', source)
        self.assertNotIn("start_translation()", source)
        self.assertIn('"outside-parent-bounds"', source)
        self.assertIn('"outside-host-horizontal-bounds"', source)
        self.assertIn('"insufficient-parent-edge-inset"', source)
        self.assertIn('"peer-button-size-mismatch"', source)


if __name__ == "__main__":
    unittest.main()
