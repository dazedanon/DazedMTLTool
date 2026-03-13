#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(pwd)"
CONFIG_FILE="$SCRIPT_DIR/patch-config.txt"

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
. "$CONFIG_FILE"

# Get the latest hash
echo "Getting latest commit SHA hash"
latest_patch_sha=$(curl -s "https://gitgud.io/api/v4/projects/$username%2F$repo/repository/branches/$branch" | jq -r '.commit.id')

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

    # Step 1: Unpack (once)
    if [ ! -d "$ROOT_DIR/data" ]; then
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
    else
        echo "[Pre-Setup] data.dts not found; skipping pre-setup SRPG steps."
    fi

download_extract() {
    # Download zip file into root
    echo "Downloading latest patch..."
    curl -sL "https://gitgud.io/$username/$repo/-/archive/$branch/$repo-$branch.zip" -o "$ROOT_DIR/repo.zip"
    if [ $? -ne 0 ]; then
        echo "Download failed!"
        rm -f "$ROOT_DIR/repo.zip"
        rm -rf "$ROOT_DIR/$repo-$branch"
        return 1
    fi

    # Extract contents, overwriting conflicts into root
    echo "Extracting..."
    unzip -qo "$ROOT_DIR/repo.zip" -d "$ROOT_DIR"
    if [ $? -ne 0 ]; then
        echo "Extraction failed!"
        rm -f "$ROOT_DIR/repo.zip"
        rm -rf "$ROOT_DIR/$repo-$branch"
        return 1
    fi

    echo "Applying patch..."
    cp -r "$ROOT_DIR/$repo-$branch/"* "$ROOT_DIR/"
    if [ $? -ne 0 ]; then
        echo "Patch application failed!"
        rm -f "$ROOT_DIR/repo.zip"
        rm -rf "$ROOT_DIR/$repo-$branch"
        return 1
    fi

    echo "Cleaning up..."
    rm -f "$ROOT_DIR/repo.zip"
    rm -rf "$ROOT_DIR/$repo-$branch"
    rm -f "$ROOT_DIR/latest_patch_sha.txt"

    # Store latest SHA for next check in gameupdate
    echo "$latest_patch_sha" > "$SCRIPT_DIR/previous_patch_sha.txt"

        # --------------------------------------------------------
        # POST-APPLY: Run Steps 3 and 4 after patch files are merged
        # 3) Apply Patch to data/project.dat
        # 4) Pack data back into data.dts
        # --------------------------------------------------------
            UNPACKER="$ROOT_DIR/SRPG_Unpacker.exe"
            if [ -f "$ROOT_DIR/data.dts" ]; then
                if [ -f "$UNPACKER" ]; then
                    echo "Running SRPG_Unpacker apply/pack steps..."

            # Step 3: Apply Patch
            if [ -f "$ROOT_DIR/data/project.dat" ]; then
                echo "Step 3: Applying patch to data/project.dat"
                ( cd "$ROOT_DIR" && "$UNPACKER" ./data/project.dat -a ) || echo "ERROR: Apply Patch failed."
            else
                echo "ERROR: data/project.dat not found; cannot apply patch."
            fi

            # Step 4: Pack
            if [ -d "$ROOT_DIR/data" ]; then
                echo "Step 4: Packing data -> data.dts"
                ( cd "$ROOT_DIR" && "$UNPACKER" -o data.dts data ) || echo "WARNING: Pack failed."
                    else
                        echo "Step 4: Skipping pack (data folder not found)."
                    fi
                    else
                        echo "SRPG_Unpacker.exe not found in root; skipping SRPG patch steps."
                    fi
                else
                    echo "data.dts not found; skipping SRPG patch steps."
                fi
}

# Check if previous_patch_sha.txt exists in gameupdate
if [ ! -f "$SCRIPT_DIR/previous_patch_sha.txt" ]; then
    echo "Previous SHA hash not found!"
    echo "Assuming first time patching..."
    download_extract
else
    # Read the stored SHA from previous check
    previous_patch_sha=$(cat "$SCRIPT_DIR/previous_patch_sha.txt")

    # Compare trimmed SHAs
    if [ "$latest_patch_sha" != "$previous_patch_sha" ]; then
        echo "Update found! Patching..."
        download_extract
    else
        echo "Patch is up to date."
    fi
fi
