#!/usr/bin/env python3
"""Launch the opt-in Electron desktop preview."""
import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Enable the persistent US$5-capped Luna runner")
    parser.add_argument("--providers", action="store_true", help="Enable normal provider execution for manual engine jobs using desktop settings (separate from capped Luna tests)")
    args = parser.parse_args()
    suffix = "electron.exe" if os.name == "nt" else "Electron.app/Contents/MacOS/Electron" if os.sys.platform == "darwin" else "electron"
    binary = ROOT / "desktop/node_modules/electron/dist" / suffix
    command = [str(binary), str(ROOT / "desktop")]
    if not binary.is_file() or not (ROOT / "desktop/dist/index.html").is_file():
        parser.error("Build the desktop first; see desktop/README.md.")
    env = {**os.environ, "DAZEDTL_DESKTOP_ALLOW_LIVE": "1" if args.live else "0"}
    env["DAZEDTL_DESKTOP_PROVIDERS"] = "1" if args.providers else "0"
    env.pop("ELECTRON_RUN_AS_NODE", None)
    return subprocess.call(command, cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
