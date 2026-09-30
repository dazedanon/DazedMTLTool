#!/usr/bin/env bash
# DazedTL one-click setup and launch for Linux/macOS.
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/setup_desktop.sh" "$@"
