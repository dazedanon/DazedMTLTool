#!/bin/bash

# Enable error handling
set -e

# Re-exec from a temp copy so applying the patch zip cannot overwrite/truncate
# this launcher while bash is still reading it (same idea as patch.sh -> patch2.sh).
if [ -z "${GAMEUPDATE_LINUX_REEXEC:-}" ]; then
    SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
    GAME_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    TMP_SELF="$(mktemp)"
    cp -f "$SELF" "$TMP_SELF"
    chmod +x "$TMP_SELF"
    export GAMEUPDATE_LINUX_REEXEC=1
    # shellcheck disable=SC2093
    exec bash "$TMP_SELF" "$GAME_ROOT"
fi

GAME_ROOT="$1"
PATCH_DIR="$GAME_ROOT/gameupdate"
REEXEC_PATH="$0"

cleanup_reexec() {
    rm -f "$REEXEC_PATH"
}
trap cleanup_reexec EXIT

cd "$GAME_ROOT"
cp "$PATCH_DIR/patch.sh" "$PATCH_DIR/patch2.sh"
set +e
bash "$PATCH_DIR/patch2.sh"
patch_exit=$?
set -e
rm -f "$PATCH_DIR/patch2.sh"

if [ "$patch_exit" -ne 0 ]; then
    echo "GameUpdate failed (exit $patch_exit)."
fi

# Match Windows patch.ps1 pause when launched interactively (double-click / terminal).
if [ -t 0 ] && [ -t 1 ]; then
    echo
    read -r -p "Press Enter to close..."
fi

exit "$patch_exit"
