#!/usr/bin/env python3
"""Launch script for DazedTL GUI."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform.startswith("linux"):
    from util.linux_desktop import configure_qt_platform

    configure_qt_platform()

# Before Qt, and it has to be before Qt: PyQt5 carries its own older Visual C++
# runtime, Windows resolves a DLL by base name against what is already loaded,
# and whichever copy wins is the one the whole process gets. Left to Qt, the
# optional inpainting models cannot load at all. Standard library only, and a
# no-op everywhere but Windows. See util/msvc_runtime.py.
from util.msvc_runtime import prepare as _prepare_msvc_runtime  # noqa: E402

_prepare_msvc_runtime()


def check_dependencies():
    """Check if required dependencies are installed."""
    from util.dependencies import missing_dependencies

    missing_deps = missing_dependencies()
    if missing_deps:
        print("Missing dependencies:")
        for dep in missing_deps:
            print(f"  - {dep}")
        print("\nPlease install them using:")
        print("  pip install -r requirements.txt")
        return False

    return True


def main():
    """Main entry point."""
    print("DazedTL GUI Launcher")
    print("=" * 40)

    from util.paths import migrate_root_data_files

    migrate_root_data_files()

    if not check_dependencies():
        sys.exit(1)

    try:
        from util.ace.update_tools import seed_ace_tools
        seed_ace_tools()
    except Exception as exc:
        print(f"Warning: Ace tool setup failed ({exc}). Ace features may be unavailable.")

    try:
        from gui.main import main as gui_main
        gui_main()
    except ImportError as e:
        print(f"Error importing GUI modules: {e}")
        print("Make sure all GUI files are in the 'gui' directory")
        sys.exit(1)
    except Exception as e:
        print(f"Error starting GUI: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
