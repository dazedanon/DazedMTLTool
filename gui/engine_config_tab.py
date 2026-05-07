"""Unified Game Engine Configuration Tab.

This tab dynamically shows the appropriate engine-specific configuration UI
based on signals from the Translation tab (engine selection).

Currently supports:
- RPG Maker MV/MZ
- Wolf RPG

Easily extensible: add new engine widget + mapping entry.
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QStackedLayout, QLabel
from PyQt5.QtCore import Qt

from gui.rpgmaker_tab import RPGMakerTab
from gui.wolf_tab import WolfTab


class EngineConfigTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_widgets()

    def _init_widgets(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        self.stack = QStackedLayout()
        layout.addLayout(self.stack)

        # Engine widgets
        self.mv_widget = RPGMakerTab("MVMZ")
        self.wolf_widget = WolfTab()

        # Placeholder when no engine selected
        self.placeholder = QLabel("Select a game engine in the Translation tab to configure its options.")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setStyleSheet("color:#888; padding:40px;")

        # Add to stack
        self.widget_map = {
            "mvmz": self.mv_widget,
            "wolf": self.wolf_widget,
        }
        self.stack.addWidget(self.placeholder)  # index 0
        for w in self.widget_map.values():
            self.stack.addWidget(w)

        self.current_engine = None
        self.show_placeholder()

    def show_placeholder(self):
        self.stack.setCurrentIndex(0)
        self.current_engine = None

    def show_engine(self, engine: str):
        engine = (engine or "").lower()
        widget = self.widget_map.get(engine)
        if not widget:
            self.show_placeholder()
            return
        # Find the widget's index in stack
        for i in range(self.stack.count()):
            if self.stack.widget(i) is widget:
                self.stack.setCurrentIndex(i)
                self.current_engine = engine
                break
