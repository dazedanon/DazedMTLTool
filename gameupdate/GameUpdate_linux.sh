#!/bin/bash

# Enable error handling
set -e

# Same layout as GameUpdate.bat: patch assets live under ./gameupdate/ next to this file.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GAME_ROOT="$SCRIPT_DIR"
PATCH_DIR="$SCRIPT_DIR/gameupdate"

cd "$GAME_ROOT"
cp "$PATCH_DIR/patch.sh" "$PATCH_DIR/patch2.sh"
bash "$PATCH_DIR/patch2.sh"
rm "$PATCH_DIR/patch2.sh"
