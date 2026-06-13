#!/usr/bin/env python3
"""
Launch script for DazedMTLTool GUI
"""

import sys
import os
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def check_dependencies():
    """Check if required dependencies are installed."""
    missing_deps = []
    
    try:
        import PyQt5
    except ImportError:
        missing_deps.append("PyQt5")
        
    try:
        from dotenv import load_dotenv
    except ImportError:
        missing_deps.append("python-dotenv")
        
    if missing_deps:
        print("Missing dependencies:")
        for dep in missing_deps:
            print(f"  - {dep}")
        print("\nPlease install them using:")
        print("  pip install -r requirements_gui.txt")
        return False
        
    return True

def main():
    """Main entry point."""
    print("DazedMTLTool GUI Launcher")
    print("=" * 40)
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)

    try:
        from util.ace.update_tools import ensure_ace_tools
        ensure_ace_tools()
    except Exception as exc:
        print(f"Warning: Ace tool setup failed ({exc}). Ace features may be unavailable.")

    try:
        from util.forge.update_tools import ensure_forge_plugins
        ensure_forge_plugins()
    except Exception as exc:
        print(f"Warning: Forge plugin setup failed ({exc}). Playtest Forge may be unavailable.")
        
    # Import and run GUI
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
