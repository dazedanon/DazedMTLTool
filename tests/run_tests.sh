#!/usr/bin/env bash
# Run DazedTL tests using the project venv (cwd = project root).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

PYTHON=""
if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
elif [[ -x "$ROOT/venv/bin/python" ]]; then
    PYTHON="$ROOT/venv/bin/python"
else
    echo "ERROR: No virtual environment found (.venv or venv)." >&2
    echo "Create one first, e.g.: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

if ! "$PYTHON" -c "import colorama, dotenv, tqdm" >/dev/null 2>&1; then
    echo "Installing test dependencies from requirements.txt..."
    "$PYTHON" -m pip install -r requirements.txt
fi

if [[ "$#" -eq 0 ]]; then
    set -- core
fi

case "$1" in
    core|extended|full)
        exec "$PYTHON" scripts/run_test_suite.py "$@"
        ;;
    *)
        # Preserve targeted unittest invocations used by contributors and docs.
        exec "$PYTHON" -m unittest "$@"
        ;;
esac
