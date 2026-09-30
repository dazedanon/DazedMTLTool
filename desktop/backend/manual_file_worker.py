"""Run the existing per-file protocol after restoring a desktop job's context."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    from desktop.backend.manual_environment import prepare
    from util.subprocess_runner import run_handler
    root, engine, filename, estimate = sys.argv[1:]
    if filename == "--files-from-stdin":
        filename = json.load(sys.stdin)
    prepare(root)
    run_handler(root, engine, filename, estimate.lower() == "true")
