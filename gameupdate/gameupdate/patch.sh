#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(pwd)"
CONFIG_FILE="$SCRIPT_DIR/patch-config.txt"
STATE_FILE="$SCRIPT_DIR/previous_patch_sha.txt"
API_HEADERS=( -H "User-Agent: GameUpdate/1.0" )

check_dependency() {
  if ! command -v "$1" > /dev/null 2>&1; then
    echo "Error: '$1' is not installed. Please install it using 'pkg install $1'."
    exit 1
  fi
}

# Run a Windows .exe. On Linux always go through wine (never rely on binfmt,
# which can hang waiting on wineserver / GUI). On Windows / Git Bash, exec directly.
run_windows_exe() {
    local exe="$1"
    shift
    case "$(uname -s)" in
        Linux*)
            if ! command -v wine > /dev/null 2>&1; then
                echo "ERROR: wine is required to run $(basename "$exe") on Linux."
                return 1
            fi
            ( cd "$ROOT_DIR" && WINEDEBUG=-all wine "$exe" "$@" )
            ;;
        *)
            ( cd "$ROOT_DIR" && "$exe" "$@" )
            ;;
    esac
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

# Defaults for older configs that only set username/repo/branch.
forge="${forge:-${provider:-gitlab}}"
host="${host:-}"
username="${username:-${owner:-${org:-}}}"
repo="${repo:-}"
branch="${branch:-}"

if [ -z "$username" ]; then
    echo "ERROR: 'username=' is missing in gameupdate/patch-config.txt"
    exit 1
fi
if [ -z "$repo" ]; then
    echo "ERROR: 'repo=' is missing in gameupdate/patch-config.txt"
    exit 1
fi
if [ -z "$branch" ]; then
    echo "ERROR: 'branch=' is missing in gameupdate/patch-config.txt"
    exit 1
fi

normalize_forge() {
    local raw
    raw="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
    case "$raw" in
        ''|gitlab|gl|gitgud) echo gitlab ;;
        github|gh) echo github ;;
        forgejo|gitea|fj|codeberg) echo forgejo ;;
        *)
            echo "ERROR: Unknown forge='$1'. Use gitlab, github, or forgejo." >&2
            return 1
            ;;
    esac
}

FORGE_KIND="$(normalize_forge "$forge")" || exit 1

# Strip scheme / path from host if a user pasted a full URL.
HOST_NAME="$(printf '%s' "$host" | sed -E 's#^https?://##; s#/.*##; s#[[:space:]]##g')"
if [ -z "$HOST_NAME" ]; then
    case "$FORGE_KIND" in
        gitlab) HOST_NAME="gitgud.io" ;;
        github) HOST_NAME="github.com" ;;
        forgejo) HOST_NAME="codeberg.org" ;;
    esac
fi

WEB_BASE="https://${HOST_NAME}"
case "$FORGE_KIND" in
    gitlab) API_BASE="${WEB_BASE}/api/v4" ;;
    github)
        if [ "$HOST_NAME" = "github.com" ]; then
            API_BASE="https://api.github.com"
        else
            API_BASE="${WEB_BASE}/api/v3"
        fi
        ;;
    forgejo) API_BASE="${WEB_BASE}/api/v1" ;;
esac

API_HEADERS=( -H "User-Agent: GameUpdate/1.0" )
if [ "$FORGE_KIND" = "github" ]; then
    API_HEADERS+=( -H "Accept: application/vnd.github+json" )
fi

owner_enc=$(jq -nr --arg s "$username" '$s | @uri')
repo_enc=$(jq -nr --arg s "$repo" '$s | @uri')
branch_enc=$(jq -nr --arg b "$branch" '$b | @uri')
project_enc=$(jq -nr --arg ns "$username" --arg rp "$repo" '$ns + "/" + $rp | @uri')

resolve_latest_sha() {
    case "$FORGE_KIND" in
        gitlab)
            curl -fsSL "${API_HEADERS[@]}" \
                "${API_BASE}/projects/${project_enc}/repository/branches/${branch_enc}" \
                | jq -r '.commit.id'
            ;;
        github)
            curl -fsSL "${API_HEADERS[@]}" \
                "${API_BASE}/repos/${owner_enc}/${repo_enc}/commits/${branch_enc}" \
                | jq -r '.sha'
            ;;
        forgejo)
            curl -fsSL "${API_HEADERS[@]}" \
                "${API_BASE}/repos/${owner_enc}/${repo_enc}/branches/${branch_enc}" \
                | jq -r '.commit.id'
            ;;
    esac
}

archive_url_for_sha() {
    local sha_enc
    sha_enc=$(jq -nr --arg s "$1" '$s | @uri')
    case "$FORGE_KIND" in
        gitlab)
            echo "${API_BASE}/projects/${project_enc}/repository/archive.zip?sha=${sha_enc}"
            ;;
        github)
            echo "${API_BASE}/repos/${owner_enc}/${repo_enc}/zipball/${sha_enc}"
            ;;
        forgejo)
            echo "${API_BASE}/repos/${owner_enc}/${repo_enc}/archive/${sha_enc}.zip"
            ;;
    esac
}

echo "Pulling patch from ${WEB_BASE}/${username}/${repo} (${FORGE_KIND}, branch: ${branch})"

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

# Get the latest hash
echo "Getting latest commit SHA hash"
latest_patch_sha=""
attempt=1
while true; do
    if latest_patch_sha="$(resolve_latest_sha)"; then
        break
    fi
    if [ "$attempt" -ge "$RETRIES" ]; then
        echo "Resolve latest patch SHA failed after $attempt attempt(s)."
        exit 1
    fi
    echo "Resolve latest patch SHA failed ($attempt/$RETRIES), retrying..."
    attempt=$((attempt + 1))
    sleep 2
done
latest_patch_sha="$(printf '%s' "$latest_patch_sha" | tr -d '[:space:]')"
if [ -z "$latest_patch_sha" ] || [ "$latest_patch_sha" = "null" ]; then
    echo "PATCH_ERR:API:Latest commit SHA response was empty."
    exit 1
fi

# --------------------------------------------------------
# PRE-SETUP: Wolf Data.wolf -> loose Data/ (before patch copy)
# --------------------------------------------------------
wolf_loose_data_ready() {
    local data_dir="$1"
    [ -d "$data_dir" ] || return 1
    [ -f "$data_dir/BasicData/CommonEvent.dat" ] && return 0
    [ -f "$data_dir/CommonEvent.dat" ] && return 0
    if compgen -G "$data_dir/*.mps" > /dev/null 2>&1; then
        return 0
    fi
    if compgen -G "$data_dir/BasicData/*.dat" > /dev/null 2>&1; then
        return 0
    fi
    return 1
}

find_uberwolf_cli() {
    if [ -f "$ROOT_DIR/UberWolfCli.exe" ]; then
        echo "$ROOT_DIR/UberWolfCli.exe"
        return 0
    fi
    if [ -f "$ROOT_DIR/gameupdate/UberWolfCli.exe" ]; then
        echo "$ROOT_DIR/gameupdate/UberWolfCli.exe"
        return 0
    fi
    return 1
}

retire_data_wolf() {
    local data_wolf="$1"
    local bak="${data_wolf}.bak"
    if [ ! -f "$data_wolf" ]; then
        return 0
    fi
    if [ ! -e "$bak" ]; then
        echo "[Pre-Setup] Retiring $(basename "$data_wolf") -> $(basename "$bak")"
        mv -f "$data_wolf" "$bak"
    else
        echo "[Pre-Setup] Removing leftover $(basename "$data_wolf") so loose Data/ takes priority"
        rm -f "$data_wolf"
    fi
}

invoke_wolf_pre_setup() {
    local data_wolf=""
    local name
    for name in Data.wolf data.wolf; do
        if [ -f "$ROOT_DIR/$name" ]; then
            data_wolf="$ROOT_DIR/$name"
            break
        fi
    done
    [ -n "$data_wolf" ] || return 0

    local data_dir="$ROOT_DIR/Data"
    if [ ! -d "$data_dir" ] && [ -d "$ROOT_DIR/data" ]; then
        data_dir="$ROOT_DIR/data"
    fi

    if wolf_loose_data_ready "$data_dir"; then
        retire_data_wolf "$data_wolf"
        return 0
    fi

    local cli
    cli="$(find_uberwolf_cli || true)"
    if [ -z "$cli" ]; then
        echo "[Pre-Setup] Data.wolf found but UberWolfCli.exe is missing."
        echo "            Copy UberWolfCli.exe into the game root (Step 1 gameupdate/) and re-run."
        return 0
    fi

    echo "[Pre-Setup] Unpacking Data.wolf with UberWolfCli (one-time)..."
    if ! run_windows_exe "$cli" -o "$data_wolf"; then
        echo "[Pre-Setup] ERROR: UberWolfCli unpack failed."
        return 0
    fi

    local unpacked="$ROOT_DIR/Data"
    if ! wolf_loose_data_ready "$unpacked"; then
        unpacked="$ROOT_DIR/data"
    fi
    if ! wolf_loose_data_ready "$unpacked"; then
        local alt
        for alt in data.wolf~ Data.wolf~ Data~ data~; do
            if [ -d "$ROOT_DIR/$alt" ]; then
                echo "[Pre-Setup] Promoting $alt -> Data/"
                rm -rf "$ROOT_DIR/Data"
                mv -f "$ROOT_DIR/$alt" "$ROOT_DIR/Data"
                unpacked="$ROOT_DIR/Data"
                break
            fi
        done
    fi

    if wolf_loose_data_ready "$unpacked"; then
        retire_data_wolf "$data_wolf"
        echo "[Pre-Setup] Wolf Data/ is ready for patching."
    else
        echo "[Pre-Setup] ERROR: Unpack finished but loose Data/ still looks empty."
    fi
}

invoke_wolf_pre_setup

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
                run_windows_exe "$UNPACKER" -o data data.dts || echo "[Pre-Setup] ERROR: Unpack failed."
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
                run_windows_exe "$UNPACKER" ./data/project.dat -c || echo "[Pre-Setup] ERROR: Create Patch failed."
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
    archive_url="$(archive_url_for_sha "$latest_patch_sha")"
    if ! retry_cmd "Download archive with curl" \
        curl -fSL --progress-bar "${API_HEADERS[@]}" \
        "$archive_url" \
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

    # Stage UberWolfCli before unpack so Data.wolf -> Data/ happens before
    # English patch files are copied on top.
    for cli_name in UberWolfCli.exe UberWolfCli.LICENSE.txt; do
        if [ -f "$inner/$cli_name" ] && [ ! -f "$ROOT_DIR/$cli_name" ]; then
            cp -f "$inner/$cli_name" "$ROOT_DIR/$cli_name"
        fi
    done
    invoke_wolf_pre_setup

    echo "Applying patch..."
    if ! cp -rf "$inner"/* "$ROOT_DIR/"; then
        echo "Patch application failed!"
        rm -rf "$TMP_EX"
        rm -f "$ROOT_DIR/repo.zip"
        return 1
    fi

    # --------------------------------------------------------
    # POST-APPLY: Run Steps 3 and 4 after patch files are merged
    # (Must finish before "Cleaning up" so a slow wine/SRPG step is not
    # mistaken for a hung cleanup - matches patch.ps1 order.)
    # --------------------------------------------------------
    UNPACKER="$ROOT_DIR/SRPG_Unpacker.exe"
    if [ -f "$ROOT_DIR/data.dts" ]; then
        if [ -f "$UNPACKER" ]; then
            echo "Running SRPG_Unpacker apply/pack steps..."

            if [ -f "$ROOT_DIR/data/project.dat" ]; then
                echo "Step 3: Applying patch to data/project.dat"
                run_windows_exe "$UNPACKER" ./data/project.dat -a || echo "ERROR: Apply Patch failed."
            else
                echo "ERROR: data/project.dat not found; cannot apply patch."
            fi

            if [ -d "$ROOT_DIR/data" ]; then
                echo "Step 4: Packing data -> data.dts"
                run_windows_exe "$UNPACKER" -o data.dts data || echo "WARNING: Pack failed."
            else
                echo "Step 4: Skipping pack (data folder not found)."
            fi
        else
            echo "SRPG_Unpacker.exe not found in root; skipping SRPG patch steps."
        fi
    fi

    # Retire Data.wolf if loose Data/ is ready after the patch copy.
    invoke_wolf_pre_setup

    echo "Cleaning up..."
    rm -rf "$TMP_EX"
    rm -f "$ROOT_DIR/repo.zip"
    # Legacy / accidental leftovers from older patchers.
    rm -rf "$ROOT_DIR/_patch_extract_tmp"
    shopt -s nullglob
    for stale in "$ROOT_DIR"/dazedmtl_patch_*.zip; do
        rm -f "$stale"
    done
    shopt -u nullglob

    echo "$latest_patch_sha" > "$STATE_FILE"
    echo "Done."
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
