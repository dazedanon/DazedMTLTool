#!/usr/bin/env bash
# One-click setup and launch, including machines without Python.
set -euo pipefail
DAZEDTL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() { echo "DazedTL setup stopped: $*" >&2; if [[ -t 0 ]]; then read -r -p 'Press Enter to close…' _reply; fi; exit 1; }

for candidate in "$DAZEDTL_ROOT/.venv/bin/python" "$DAZEDTL_ROOT/venv/bin/python" python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -I -c 'import sys; raise SystemExit(sys.version_info < (3,12))' >/dev/null 2>&1; then
    exec "$candidate" -I -B "$DAZEDTL_ROOT/scripts/setup_desktop.py" "$@"
  fi
done

case "$(uname -s)" in
  Linux) platform_name=linux; default_cache="${XDG_CACHE_HOME:-$HOME/.cache}/DazedTL/setup" ;;
  Darwin) platform_name=darwin; default_cache="$HOME/Library/Caches/DazedTL/setup" ;;
  *) fail 'Use START.bat on Windows.' ;;
esac
case "$(uname -m)" in
  x86_64|amd64) architecture=x64 ;;
  aarch64|arm64) architecture=arm64 ;;
  *) fail 'A 64-bit x86 or ARM operating system is required.' ;;
esac
bootstrap_cache="${DAZEDTL_SETUP_HOME:-$default_cache}"
manifest="$DAZEDTL_ROOT/desktop/setup-runtimes.json"
manifest_value() { awk -F '"' -v key="$1" '$2 == key { print $4; exit }' "$manifest"; }
uv_version="$(manifest_value uv_version)"
python_version="$(manifest_value python_version)"
uv_url="$(manifest_value "uv_${platform_name}_${architecture}_url")"
uv_hash="$(manifest_value "uv_${platform_name}_${architecture}_sha256")"
[[ "$uv_url" == https://* && "$uv_hash" =~ ^[0-9a-f]{64}$ ]] || fail 'The setup download manifest is incomplete.'
uv_folder="$bootstrap_cache/shell-uv-$uv_version-${platform_name}_$architecture"
uv_executable="$uv_folder/uv"
mkdir -p "$bootstrap_cache"
offline_arguments=()
for argument in "$@"; do [[ "$argument" != --offline ]] || offline_arguments=(--offline); done
cached_hash=""
if [[ -f "$uv_folder/verified.json" ]]; then
  cached_hash="$(awk -F '"' '$2 == "archive" { print $4; exit }' "$uv_folder/verified.json")"
fi
if [[ ! -x "$uv_executable" || "$cached_hash" != "$uv_hash" ]]; then
  [[ ${#offline_arguments[@]} -eq 0 ]] || fail 'Connect once to download the private application runtimes.'
  temporary="$(mktemp -d "$bootstrap_cache/uv-download.XXXXXX")"
  trap 'rm -rf -- "$temporary"' EXIT
  echo 'Downloading the verified Python setup tool…'
  if command -v curl >/dev/null 2>&1; then
    curl --fail --location --proto '=https' --proto-redir '=https' --retry 2 --output "$temporary/uv.tar.gz" "$uv_url" || fail 'The runtime download failed. Check your connection and try again.'
  elif command -v wget >/dev/null 2>&1; then
    wget --https-only --output-document="$temporary/uv.tar.gz" "$uv_url" || fail 'The runtime download failed.'
  else
    fail 'This system needs curl or wget to download the app runtimes.'
  fi
  if command -v sha256sum >/dev/null 2>&1; then
    actual_hash="$(sha256sum "$temporary/uv.tar.gz" | awk '{print $1}')"
  else
    actual_hash="$(shasum -a 256 "$temporary/uv.tar.gz" | awk '{print $1}')"
  fi
  [[ "$actual_hash" == "$uv_hash" ]] || fail 'Download verification failed; nothing was installed.'
  tar -xzf "$temporary/uv.tar.gz" -C "$temporary"
  uv_download="$(find "$temporary" -type f -name uv -print -quit)"
  [[ -n "$uv_download" ]] || fail 'The runtime archive is incomplete.'
  mkdir -p "$uv_folder"
  cp "$uv_download" "$uv_executable"
  chmod 755 "$uv_executable"
  printf '{"archive":"%s"}\n' "$uv_hash" > "$uv_folder/verified.json"
fi
export UV_PYTHON_INSTALL_DIR="$bootstrap_cache/pythons" UV_CACHE_DIR="$bootstrap_cache/uv-cache"
echo 'Preparing a private Python runtime…'
"$uv_executable" --no-config "${offline_arguments[@]}" python install "$python_version" --no-bin --no-registry || fail 'Python setup failed. Launch again to retry.'
managed_python="$("$uv_executable" --no-config "${offline_arguments[@]}" python find --managed-python --no-project "$python_version")"
exec "$managed_python" -I -B "$DAZEDTL_ROOT/scripts/setup_desktop.py" "$@"
