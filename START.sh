#!/usr/bin/env bash
# DazedMTLTool startup script for Linux/macOS

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

NEED_VENV_CREATE=0
VENV_DIR=""
CREATE_VENV_DIR=""
FOUND_PYTHON=""

pause_on_error() {
    if [[ -t 0 ]]; then
        read -r -p "Press Enter to exit..."
    fi
}

die() {
    echo "ERROR: $*"
    pause_on_error
    exit 1
}

python_version_ok() {
    local version="$1"
    local major="${version%%.*}"
    local rest="${version#*.}"
    local minor="${rest%%.*}"

    [[ "$major" == "3" && "$minor" -ge 12 && "$minor" -lt 15 ]]
}

get_python_version() {
    "$1" --version 2>&1 | awk '{print $2}'
}

check_python_version() {
    [[ -n "$FOUND_PYTHON" ]] && return 0
    local py="$1"
    [[ -n "$py" && -x "$py" ]] || return 0

    local ver
    ver="$(get_python_version "$py" 2>/dev/null)" || return 0
    if python_version_ok "$ver"; then
        FOUND_PYTHON="$py"
    fi
}

find_suitable_python() {
    FOUND_PYTHON=""
    local py candidate

    while IFS= read -r py; do
        check_python_version "$py"
        [[ -n "$FOUND_PYTHON" ]] && return 0
    done < <(type -a python3 python 2>/dev/null | awk '/ is / {print $NF}' | awk '!seen[$0]++')

    for candidate in python3.14 python3.13 python3.12 python3 python; do
        py="$(command -v "$candidate" 2>/dev/null || true)"
        check_python_version "$py"
        [[ -n "$FOUND_PYTHON" ]] && return 0
    done

    return 1
}

backup_venv() {
    local target_dir="${1:-.venv}"
    local bak_idx=1

    while [[ -d "${target_dir}.bak_${bak_idx}" ]]; do
        ((bak_idx++))
    done

    if mv "$target_dir" "${target_dir}.bak_${bak_idx}"; then
        echo "$target_dir renamed to ${target_dir}.bak_${bak_idx}"
    else
        echo "ERROR: Failed to back up $target_dir to ${target_dir}.bak_${bak_idx}."
        echo "Please ensure no files are locked and try again."
        return 1
    fi
}

create_venv() {
    [[ -n "$CREATE_VENV_DIR" ]] || CREATE_VENV_DIR=".venv"
    echo "Creating new $CREATE_VENV_DIR using $FOUND_PYTHON ..."
    if ! "$FOUND_PYTHON" -m venv "$CREATE_VENV_DIR"; then
        die "Failed to create virtual environment."
    fi
    echo "Virtual environment created"
    echo
    VENV_DIR="$CREATE_VENV_DIR"
}

activate_venv() {
    echo "Activating virtual environment..."
    # shellcheck source=/dev/null
    if source "$VENV_DIR/bin/activate"; then
        echo "Virtual environment activated"
        echo
        return 0
    fi

    echo "ERROR: Failed to activate virtual environment at \"$VENV_DIR\"."
    echo "Attempting to recreate the virtual environment with a compatible Python..."
    CREATE_VENV_DIR="$VENV_DIR"
    backup_venv "$VENV_DIR" || die "Failed to back up existing virtual environment."

    if ! find_suitable_python; then
        die "No suitable Python (>=3.12 and <3.15) found in PATH for recreation."
    fi

    echo "Recreating $CREATE_VENV_DIR using $FOUND_PYTHON ..."
    if ! "$FOUND_PYTHON" -m venv "$CREATE_VENV_DIR"; then
        die "Failed to create virtual environment during recreation."
    fi
    VENV_DIR="$CREATE_VENV_DIR"
    echo "Retrying activation..."
    # shellcheck source=/dev/null
    if ! source "$VENV_DIR/bin/activate"; then
        die "Activation failed after recreation."
    fi
    echo "Virtual environment activated"
    echo
}

ensure_vocab_file() {
    mkdir -p data
    if [[ -f "data/vocab.txt" ]]; then
        return 0
    fi

    if [[ -f "data/vocab_base.txt" ]]; then
        echo "data/vocab.txt not found - creating from data/vocab_base.txt..."
        if cp "data/vocab_base.txt" "data/vocab.txt"; then
            echo "Created data/vocab.txt from data/vocab_base.txt"
        else
            echo "ERROR: Failed to copy data/vocab_base.txt to data/vocab.txt."
        fi
    else
        echo "data/vocab.txt not found - creating empty file to avoid import errors..."
        if : > "data/vocab.txt"; then
            echo "Created empty data/vocab.txt"
        else
            echo "ERROR: Failed to create empty data/vocab.txt."
        fi
    fi
}

echo "=========================================="
echo "   DazedMTLTool Startup Script"
echo "=========================================="
echo

echo "[1/4] Checking for a virtual environment..."
if [[ -d ".venv" ]]; then
    VENV_DIR=".venv"
elif [[ -d "venv" ]]; then
    VENV_DIR="venv"
fi

if [[ -n "$VENV_DIR" ]]; then
    echo "$VENV_DIR found. Checking its Python version..."
    venv_python="$VENV_DIR/bin/python"
    if [[ ! -x "$venv_python" ]]; then
        echo "ERROR: Python executable not found at \"$venv_python\"."
        CREATE_VENV_DIR="$VENV_DIR"
        backup_venv "$VENV_DIR" || die "Failed to back up existing virtual environment."
        NEED_VENV_CREATE=1
    else
        venv_python_version="$(get_python_version "$venv_python" 2>/dev/null || true)"
        if [[ -z "$venv_python_version" ]]; then
            echo "ERROR: Could not determine Python version from \"$venv_python\"."
            CREATE_VENV_DIR="$VENV_DIR"
            backup_venv "$VENV_DIR" || die "Failed to back up existing virtual environment."
            NEED_VENV_CREATE=1
        else
            echo "Detected Python version: $venv_python_version"
            if python_version_ok "$venv_python_version"; then
                echo "$VENV_DIR Python version $venv_python_version is compatible (>=3.12 and <3.15)."
            else
                echo "$VENV_DIR Python version $venv_python_version is not supported (requires >=3.12 and <3.15)"
                echo "Backing up $VENV_DIR..."
                CREATE_VENV_DIR="$VENV_DIR"
                backup_venv "$VENV_DIR" || die "Failed to back up existing virtual environment."
                NEED_VENV_CREATE=1
            fi
        fi
    fi
else
    echo "No existing virtual environment found."
    CREATE_VENV_DIR=".venv"
    NEED_VENV_CREATE=1
fi
echo

if [[ "$NEED_VENV_CREATE" -eq 1 ]]; then
    echo "[2/4] Finding a compatible Python..."
    if ! find_suitable_python; then
        die "No suitable Python (>=3.12 and <3.15) found in PATH. Please install Python 3.12, 3.13, or 3.14 and ensure it is in your PATH."
    fi
    create_venv
fi

activate_venv

echo "Checking dependencies..."
echo "Checking if requirements are satisfied..."
if ! python -c "import PyQt5; import openai; import dotenv; import PIL; import anthropic; print('All dependencies satisfied')" >/dev/null 2>&1; then
    echo "Upgrading pip..."
    python -m pip install --upgrade pip >/dev/null 2>&1
    echo "Installing/updating requirements..."
    if ! pip install -r requirements.txt; then
        die "Failed to install requirements."
    fi
    echo "Dependencies installed successfully"
else
    echo "All dependencies are already satisfied"
fi
echo

echo "=========================================="
echo "   Launching DazedMTLTool GUI..."
echo "=========================================="
echo

ensure_vocab_file

if ! exec python "$SCRIPT_DIR/scripts/start_gui.py"; then
    echo
    echo "ERROR: Failed to launch GUI."
    echo "Check the error messages above."
    pause_on_error
    exit 1
fi

echo
echo "GUI closed successfully."
