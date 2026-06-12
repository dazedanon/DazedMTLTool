"""TL Inspector install helpers for RPG Maker MV/MZ (Idea: Sakura · Plugin: Kao_SSS)."""

from util.tl_inspector.config import detect_editors, load_config, save_config
from util.tl_inspector.installer import apply_config, bundled_plugin_path, detect_engine, install, status, uninstall

__all__ = [
    "apply_config",
    "bundled_plugin_path",
    "detect_editors",
    "detect_engine",
    "install",
    "load_config",
    "save_config",
    "status",
    "uninstall",
]
