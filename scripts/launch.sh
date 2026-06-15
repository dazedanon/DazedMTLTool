#!/usr/bin/env bash
# Launcher for DazedMTLTool.desktop (finds venv, then starts the GUI).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

PYTHON="python3"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
elif [[ -x "$ROOT/venv/bin/python" ]]; then
    PYTHON="$ROOT/venv/bin/python"
fi

exec "$PYTHON" "$ROOT/scripts/start_gui.py"
