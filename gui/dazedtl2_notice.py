"""Points users of this tool to DazedTL 2.0, which replaces it."""

from __future__ import annotations

from PyQt5.QtCore import QSettings, Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from gui.theme import COLORS
from util.paths import APP_NAME, ORG_NAME

DOWNLOADS = (
    ("GitGud", "https://gitgud.io/DazedAnon/dazedtl"),
    ("git.dazedtl.dev", "https://git.dazedtl.dev/dazed/DazedTL"),
)
SEEN_KEY = "notices/dazedtl2Seen"


class DazedTL2Dialog(QDialog):
    """Explains what 2.0 is, how it installs, and where to download it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DazedTL 2.0")
        self.setMinimumWidth(520)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        heading = QVBoxLayout()
        heading.setSpacing(4)
        eyebrow = QLabel("New version")
        eyebrow.setObjectName("appPageEyebrow")
        title = QLabel("DazedTL 2.0 is here")
        title.setObjectName("appPageTitle")
        heading.addWidget(eyebrow)
        heading.addWidget(title)
        layout.addLayout(heading)

        for text in (
            "DazedTL 2.0 is a new app that replaces this one. RPG Maker MV/MZ and Ace "
            "games get a guided workflow, a coding assistant can translate any other "
            "engine, and it updates itself safely.",
            "This version keeps working, but new features and fixes go into 2.0.",
            "2.0 installs separately: download it, unpack it into a new folder and run "
            "START. Nothing else needs to be installed first. Add your API key again in "
            "its Settings; your games and translations stay where they are.",
        ):
            label = QLabel(text)
            label.setObjectName("appPagePurpose")
            label.setWordWrap(True)
            layout.addWidget(label)

        links = QLabel(
            "Download from "
            + " or ".join(
                f'<a href="{url}" style="color: {COLORS.accent_text};">{name}</a>'
                for name, url in DOWNLOADS
            )
            + "."
        )
        links.setObjectName("appPagePurpose")
        links.setTextFormat(Qt.RichText)
        links.setTextInteractionFlags(Qt.TextBrowserInteraction)
        links.setOpenExternalLinks(True)
        layout.addWidget(links)

        buttons = QHBoxLayout()
        buttons.addStretch()
        from gui.ui_components import configure_action_button

        later = QPushButton("Later")
        configure_action_button(later, variant="quiet")
        later.clicked.connect(self.reject)
        download = QPushButton("Open the download page")
        configure_action_button(download, variant="primary")
        download.clicked.connect(self._open_download)
        buttons.addWidget(later)
        buttons.addWidget(download)
        layout.addSpacing(4)
        layout.addLayout(buttons)
        # Wrapped labels report a taller size hint than they need at this width.
        self.resize(self.minimumWidth(), layout.totalHeightForWidth(self.minimumWidth()))

    def _open_download(self):
        QDesktopServices.openUrl(QUrl(DOWNLOADS[0][1]))
        self.accept()


def show_once(parent) -> bool:
    """Shows the notice the first time this install starts after the update."""
    settings = QSettings(ORG_NAME, APP_NAME)
    if settings.value(SEEN_KEY, False, type=bool):
        return False
    settings.setValue(SEEN_KEY, True)
    DazedTL2Dialog(parent).exec_()
    return True
