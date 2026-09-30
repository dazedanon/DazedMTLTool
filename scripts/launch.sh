#!/usr/bin/env bash
# Desktop-entry bridge to the same one-click setup used by fresh installs.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

# Shortcuts installed by the Qt app used Terminal=false. Show setup progress
# through an available terminal until those shortcuts are replaced.
if [[ ! -t 1 ]]; then
    if command -v x-terminal-emulator >/dev/null 2>&1; then
        exec x-terminal-emulator -e bash "$ROOT/START.sh" "$@"
    elif command -v gnome-terminal >/dev/null 2>&1; then
        exec gnome-terminal -- bash "$ROOT/START.sh" "$@"
    elif command -v konsole >/dev/null 2>&1; then
        exec konsole -e bash "$ROOT/START.sh" "$@"
    fi
fi
exec bash "$ROOT/START.sh" "$@"
