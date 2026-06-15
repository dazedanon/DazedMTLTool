#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(pwd)"
CONFIG_FILE="$SCRIPT_DIR/patch-config.txt"
STATE_FILE="$SCRIPT_DIR/previous_patch_sha.txt"
GITGUD_API="https://gitgud.io/api/v4"
API_HEADERS=( -H "User-Agent: GameUpdate/1.0" )

check_dependency() {
  if ! command -v "$1" > /dev/null 2>&1; then
    echo "Error: '$1' is not installed. Please install it using 'pkg install $1'."
    exit 1
  fi
}

# Check for jq, unzip, and curl
check_dependency jq
check_dependency unzip
check_dependency curl

# Check if CONFIG_FILE exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Config file '$CONFIG_FILE' not found! Assuming no patching needed."
    exit 0
fi

# Convert line endings to Unix format
sed -i 's/\r$//' "$CONFIG_FILE"

# Debug information
echo "Root directory: $ROOT_DIR"
echo "Config file path: $CONFIG_FILE"

# Read configuration from file
# shellcheck disable=SC1090
. "$CONFIG_FILE"

if [ -z "${username:-}" ]; then
    echo "ERROR: 'username=' is missing in gameupdate/patch-config.txt"
    exit 1
fi
if [ -z "${repo:-}" ]; then
    echo "ERROR: 'repo=' is missing in gameupdate/patch-config.txt"
    exit 1
fi
if [ -z "${branch:-}" ]; then
    echo "ERROR: 'branch=' is missing in gameupdate/patch-config.txt"
    exit 1
fi

RETRIES="${GAMEUPDATE_DL_ATTEMPTS:-2}"
if ! [[ "$RETRIES" =~ ^[1-9][0-9]*$ ]]; then
    RETRIES=2
fi

retry_cmd() {
    local name="$1"
    shift
    local attempt=1
    while true; do
        if "$@"; then
            return 0
        fi
        if [ "$attempt" -ge "$RETRIES" ]; then
            echo "$name failed after $attempt attempt(s)."
            return 1
        fi
        echo "$name failed ($attempt/$RETRIES), retrying..."
        attempt=$((attempt + 1))
        sleep 2
    done
}

project_enc=$(jq -nr --arg ns "$username" --arg rp "$repo" '$ns + "/" + $rp | @uri')
branch_enc=$(jq -nr --arg b "$branch" '$b | @uri')

# Get the latest hash
echo "Getting latest commit SHA hash"
latest_patch_sha="$(
  retry_cmd "Resolve latest patch SHA" \
    curl -fsSL "${API_HEADERS[@]}" \
    "${GITGUD_API}/projects/${project_enc}/repository/branches/${branch_enc}" \
  | jq -r '.commit.id'
)"
latest_patch_sha="$(printf '%s' "$latest_patch_sha" | tr -d '[:space:]')"
if [ -z "$latest_patch_sha" ] || [ "$latest_patch_sha" = "null" ]; then
    echo "PATCH_ERR:API:Latest commit SHA response was empty."
    exit 1
fi

# --------------------------------------------------------
# PRE-SETUP: Ensure SRPG data and patch structure exists
# Run Steps 1 and 2 BEFORE pulling repo patch to avoid overwriting updates
# 1) Unpack once if data folder doesn't exist (and data.dts does)
# 2) Create Patch once if patch folder doesn't exist
# --------------------------------------------------------
UNPACKER="$ROOT_DIR/SRPG_Unpacker.exe"
if [ -f "$ROOT_DIR/data.dts" ]; then
    if [ -f "$UNPACKER" ]; then
        echo "[Pre-Setup] Running SRPG_Unpacker preparation steps..."

        # Step 1: Unpack (once) — mirror patch.ps1: unpack if no data/ or no data/project.dat
        if [ ! -d "$ROOT_DIR/data" ] || [ ! -f "$ROOT_DIR/data/project.dat" ]; then
            if [ -f "$ROOT_DIR/data.dts" ]; then
                echo "[Pre-Setup] Step 1: Unpacking data.dts -> data"
                ( cd "$ROOT_DIR" && "$UNPACKER" -o data data.dts ) || echo "[Pre-Setup] ERROR: Unpack failed."
            else
                echo "[Pre-Setup] Step 1: Skipping unpack (no data folder and no data.dts found)."
            fi
        else
            echo "[Pre-Setup] Step 1: data folder exists; skipping unpack."
        fi

        # Step 2: Create Patch (once)
        if [ ! -d "$ROOT_DIR/patch" ]; then
            if [ -f "$ROOT_DIR/data/project.dat" ]; then
                echo "[Pre-Setup] Step 2: Creating patch from data/project.dat"
                ( cd "$ROOT_DIR" && "$UNPACKER" ./data/project.dat -c ) || echo "[Pre-Setup] ERROR: Create Patch failed."
            else
                echo "[Pre-Setup] Step 2: Skipping create patch (data/project.dat not found)."
            fi
        else
            echo "[Pre-Setup] Step 2: patch folder exists; skipping create."
        fi
    else
        echo "[Pre-Setup] SRPG_Unpacker.exe not found in root; skipping pre-setup steps."
    fi
fi

download_extract() {
    echo "Downloading latest patch..."
    archive_sha_enc=$(jq -nr --arg s "$latest_patch_sha" '$s | @uri')
    if ! retry_cmd "Download archive with curl" \
        curl -fSL --progress-bar "${API_HEADERS[@]}" \
        "${GITGUD_API}/projects/${project_enc}/repository/archive.zip?sha=${archive_sha_enc}" \
        -o "$ROOT_DIR/repo.zip"; then
        echo "Download failed!"
        rm -f "$ROOT_DIR/repo.zip"
        return 1
    fi

    TMP_EX=$(mktemp -d)

    echo "Extracting..."
    if ! unzip -qo "$ROOT_DIR/repo.zip" -d "$TMP_EX"; then
        echo "Extraction failed!"
        rm -rf "$TMP_EX"
        rm -f "$ROOT_DIR/repo.zip"
        return 1
    fi

    inner=""
    for d in "$TMP_EX"/*; do
        if [ -d "$d" ]; then
            inner="$d"
            break
        fi
    done
    if [ -z "$inner" ]; then
        echo "Archive had no root folder!"
        rm -rf "$TMP_EX"
        rm -f "$ROOT_DIR/repo.zip"
        return 1
    fi

    echo "Applying patch..."
    if ! cp -r "$inner"/* "$ROOT_DIR/"; then
        echo "Patch application failed!"
        rm -rf "$TMP_EX"
        rm -f "$ROOT_DIR/repo.zip"
        return 1
    fi

    rm -rf "$TMP_EX"

    echo "Cleaning up..."
    rm -f "$ROOT_DIR/repo.zip"

    # --------------------------------------------------------
    # POST-APPLY: Run Steps 3 and 4 after patch files are merged
    # --------------------------------------------------------
    UNPACKER="$ROOT_DIR/SRPG_Unpacker.exe"
    if [ -f "$ROOT_DIR/data.dts" ]; then
        if [ -f "$UNPACKER" ]; then
            echo "Running SRPG_Unpacker apply/pack steps..."

            if [ -f "$ROOT_DIR/data/project.dat" ]; then
                echo "Step 3: Applying patch to data/project.dat"
                ( cd "$ROOT_DIR" && "$UNPACKER" ./data/project.dat -a ) || echo "ERROR: Apply Patch failed."
            else
                echo "ERROR: data/project.dat not found; cannot apply patch."
            fi

            if [ -d "$ROOT_DIR/data" ]; then
                echo "Step 4: Packing data -> data.dts"
                ( cd "$ROOT_DIR" && "$UNPACKER" -o data.dts data ) || echo "WARNING: Pack failed."
            else
                echo "Step 4: Skipping pack (data folder not found)."
            fi
        else
            echo "SRPG_Unpacker.exe not found in root; skipping SRPG patch steps."
        fi
    fi

    echo "$latest_patch_sha" > "$STATE_FILE"
}

# Check if previous_patch_sha.txt exists in gameupdate
if [ ! -f "$STATE_FILE" ]; then
    echo "No saved patch version yet (first run); comparing with remote..."
    download_extract
else
    previous_patch_sha=$(tr -d '[:space:]' < "$STATE_FILE")

    if [ "$latest_patch_sha" != "$previous_patch_sha" ]; then
        echo "Update found! Patching..."
        download_extract
    else
        echo "Already up to date (matches latest patch commit)."
    fi
fi
