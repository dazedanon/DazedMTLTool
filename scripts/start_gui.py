#!/usr/bin/env python3
"""Launch script for DazedTL GUI."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform.startswith("linux"):
    from util.linux_desktop import configure_qt_platform

    configure_qt_platform()


def check_dependencies():
    """Check if required dependencies are installed."""
    missing_deps = []

    try:
        import PyQt5  # noqa: F401
    except ImportError:
        missing_deps.append("PyQt5")

    try:
        from dotenv import load_dotenv  # noqa: F401
    except ImportError:
        missing_deps.append("python-dotenv")

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
        from util.forge.update_tools import seed_forge_plugins
        seed_forge_plugins()
    except Exception as exc:
        print(f"Warning: Forge plugin setup failed ({exc}). Playtest Forge may be unavailable.")

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
