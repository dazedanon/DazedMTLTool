"""
DazedTL GUI Package
"""

__version__ = "1.0.0"
__author__ = "DazedTranslations"

# Package imports
from .main import DazedMTLGUI
from .config_tab import ConfigTab
from .rpgmaker_tab import RPGMakerTab
from .log_viewer import LogViewer
from .file_manager import FileManager
from .workflow_tab import WorkflowTab
from .evaluation_tab import EvaluationTab

__all__ = [
    "DazedMTLGUI",
    "ConfigTab",
    "RPGMakerTab",
    "LogViewer",
    "FileManager",
    "WorkflowTab",
    "EvaluationTab",
]
