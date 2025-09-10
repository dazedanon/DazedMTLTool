"""Wolf RPG configuration tab (basic initial implementation).

Provides toggles for a subset of flags in wolf.py so users can enable/disable
what gets translated. This can be expanded later.
"""
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QCheckBox, QPushButton, QMessageBox, QLabel, QHBoxLayout, QScrollArea
)
from PyQt5.QtCore import pyqtSignal
import re

class WolfTab(QWidget):
    config_changed = pyqtSignal()

    DEFAULT_CONFIG = {
        # Dialogue/choices
        "CODE101": True,
        "CODE102": True,
        # Picture
        "CODE150": True,
        # Strings / variables
        "CODE122": True,
        # Other
        "CODE210": True,
        "CODE300": True,
        "CODE250": True,
        # Database flags
        "SCENARIOFLAG": True,
        "OPTIONSFLAG": True,
        "NPCFLAG": True,
        "DBNAMEFLAG": True,
        "DBVALUEFLAG": True,
        "ITEMFLAG": True,
        "STATEFLAG": True,
        "ENEMYFLAG": True,
        "ARMORFLAG": True,
        "WEAPONFLAG": True,
        "SKILLFLAG": True,
    }

    def __init__(self):
        super().__init__()
        self.init_ui()
        self.reset_to_defaults()

    def init_ui(self):
        main_layout = QVBoxLayout()
        scroll = QScrollArea()
        content = QWidget()
        v = QVBoxLayout()

        title = QLabel("Wolf RPG Settings")
        title.setStyleSheet("font-size:16px;font-weight:bold;color:#007acc")
        v.addWidget(title)
        desc = QLabel("Toggle which parts of Wolf RPG data are translated. This is a minimal first pass; more options can be added later.")
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#cccccc")
        v.addWidget(desc)

        # Groups
        self.checkboxes = {}
        self.add_group(v, "Dialogue / Choices", ["CODE101", "CODE102"])
        self.add_group(v, "Pictures / Variables", ["CODE150", "CODE122"])    
        self.add_group(v, "Other Event Codes", ["CODE210", "CODE300", "CODE250"])    
        self.add_group(v, "Database Sections", [
            "SCENARIOFLAG", "OPTIONSFLAG", "NPCFLAG", "DBNAMEFLAG", "DBVALUEFLAG",
            "ITEMFLAG", "STATEFLAG", "ENEMYFLAG", "ARMORFLAG", "WEAPONFLAG", "SKILLFLAG"
        ])

        # Buttons
        btn_row = QHBoxLayout()
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.reset_to_defaults)
        self.apply_btn = QPushButton("Apply Now")
        self.apply_btn.clicked.connect(self.apply_to_module)
        btn_row.addWidget(self.reset_btn)
        btn_row.addWidget(self.apply_btn)
        btn_row.addStretch()
        v.addLayout(btn_row)

        content.setLayout(v)
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        main_layout.addWidget(scroll)
        self.setLayout(main_layout)

    def add_group(self, parent_layout, title, keys):
        box = QGroupBox(title)
        v = QVBoxLayout()
        for k in keys:
            cb = QCheckBox(k)
            cb.stateChanged.connect(lambda _=None: self.apply_to_module(False))
            v.addWidget(cb)
            self.checkboxes[k] = cb
        box.setLayout(v)
        parent_layout.addWidget(box)

    def get_config(self):
        return {k: cb.isChecked() for k, cb in self.checkboxes.items()}

    def reset_to_defaults(self):
        for k, val in self.DEFAULT_CONFIG.items():
            if k in self.checkboxes:
                self.checkboxes[k].setChecked(val)
        self.apply_to_module()

    def apply_to_module(self, show_message=False):
        module_path = Path(__file__).parent.parent / 'modules' / 'wolf.py'
        if not module_path.exists():
            if show_message:
                QMessageBox.critical(self, 'Error', 'wolf.py not found in modules directory.')
            return
        try:
            content = module_path.read_text(encoding='utf-8')
            for key, value in self.get_config().items():
                pattern = rf'^{key}\s*=\s*.*$'
                content = re.sub(pattern, f'{key} = {value}', content, flags=re.MULTILINE)
            module_path.write_text(content, encoding='utf-8')
            self.config_changed.emit()
            if show_message:
                QMessageBox.information(self, 'Applied', 'Wolf configuration applied to wolf.py')
        except Exception as e:
            if show_message:
                QMessageBox.critical(self, 'Error', f'Failed to apply settings: {e}')

