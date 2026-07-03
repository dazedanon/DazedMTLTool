"""WolfDawn CLI bootstrap and thin subprocess wrappers.

WolfDawn is the vendored Rust toolchain under ``util/wolfdawn-master`` that
unpacks, extracts, injects, and repacks WOLF RPG Editor game data. It ships as
source, so the ``wolf`` binary is built on demand with ``cargo build --release``
the first time it is needed (mirrors the on-demand tool bootstrap in
``util/ace``). Everything the DazedMTLTool Wolf workflow needs goes through the
helpers here so command syntax and exit-code handling live in one place.

Exit codes emitted by ``wolf`` (see crates/wolf-cli/src/main.rs):
    0   success
    2   round-trip mismatch / inject guard / name-consistency failure
    4   read / parse / write / crypto failure
    64  usage error (bad arguments / unknown subcommand)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence, Union

__all__ = [
    "WolfDawnError",
    "WolfResult",
    "wolfdawn_source_dir",
    "wolf_binary_path",
    "ensure_wolf_binary",
    "unpack_all",
    "strings_extract",
    "names_extract",
    "strings_inject",
    "names_inject",
    "pack",
    "save_update",
    "names_check",
]

# ``util/wolfdawn`` -> repo root is two parents up; the vendored source sits at
# ``util/wolfdawn-master``.
_PACKAGE_DIR = Path(__file__).resolve().parent
_UTIL_DIR = _PACKAGE_DIR.parent
_SOURCE_DIR = _UTIL_DIR / "wolfdawn-master"
# Committed, prebuilt binaries live here (per-platform) so end users don't need a
# Rust toolchain. A build is only attempted when no bundled binary is present.
_BUNDLED_DIR = _PACKAGE_DIR / "bin"

PathLike = Union[str, Path]


class WolfDawnError(RuntimeError):
    """Raised when the WolfDawn binary can't be built/located or a command fails hard."""


@dataclass
class WolfResult:
    """Outcome of a single ``wolf`` invocation."""

    returncode: int
    stdout: str
    stderr: str
    argv: list[str]

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def raise_for_status(self) -> "WolfResult":
        if not self.ok:
            raise WolfDawnError(
                f"wolf {' '.join(self.argv[1:])} exited {self.returncode}: "
                f"{(self.stderr or self.stdout).strip()}"
            )
        return self


def wolfdawn_source_dir() -> Path:
    """Absolute path to the vendored WolfDawn Rust workspace."""
    return _SOURCE_DIR


def _exe_name() -> str:
    return "wolf.exe" if sys.platform.startswith("win") else "wolf"


def _platform_dir() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def bundled_binary_path() -> Path:
    """Committed prebuilt binary path for the current platform (may not exist)."""
    return _BUNDLED_DIR / _platform_dir() / _exe_name()


def _built_binary_path() -> Path:
    """Path of a locally cargo-built binary under the source tree's target/."""
    return _SOURCE_DIR / "target" / "release" / _exe_name()


def wolf_binary_path() -> Path:
    """Preferred ``wolf`` binary path: bundled if present, else the built path."""
    bundled = bundled_binary_path()
    if bundled.is_file():
        return bundled
    return _built_binary_path()


def _persist_binary(src: Path, log_fn=None) -> Path:
    """Copy a freshly built binary into the committed per-platform bundle dir."""
    dest = bundled_binary_path()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        dest.chmod(0o755)
        _log(f"Saved WolfDawn binary to {dest}", log_fn)
        return dest
    except Exception as exc:  # pragma: no cover - best effort persistence
        _log(f"Warning: could not persist WolfDawn binary to {dest}: {exc}", log_fn)
        return src


def ensure_wolf_binary(force: bool = False, log_fn=print) -> Path:
    """Return the ``wolf`` binary path, building it with cargo only if needed.

    Resolution order:
      1. Committed, prebuilt binary under ``util/wolfdawn/bin/<platform>/`` — used
         directly so end users never need a Rust toolchain.
      2. A locally cargo-built binary under the source ``target/release``.
      3. Build from source with ``cargo build --release`` and persist the result
         into the committed bundle dir for reuse.

    Raises :class:`WolfDawnError` with actionable guidance when the source tree
    is missing, ``cargo`` is not on PATH, or the build fails.
    """
    if not force:
        bundled = bundled_binary_path()
        if bundled.is_file():
            return bundled
        built = _built_binary_path()
        if built.is_file():
            return _persist_binary(built, log_fn)

    if not _SOURCE_DIR.is_dir():
        raise WolfDawnError(
            f"WolfDawn source not found at {_SOURCE_DIR}. The vendored "
            "'wolfdawn-master' tree is required to build the 'wolf' CLI."
        )

    cargo = shutil.which("cargo")
    if not cargo:
        raise WolfDawnError(
            "WolfDawn needs to be compiled but 'cargo' (the Rust toolchain) was "
            "not found on PATH. Install Rust from https://rustup.rs/ and try "
            "again, or place a prebuilt binary at "
            f"{bundled_binary_path()}."
        )

    _log(f"Building WolfDawn 'wolf' binary (cargo build --release) in {_SOURCE_DIR} ...", log_fn)
    try:
        proc = subprocess.run(
            [cargo, "build", "--release", "--bin", "wolf"],
            cwd=str(_SOURCE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:  # pragma: no cover - subprocess spawn failure
        raise WolfDawnError(f"Failed to run cargo build for WolfDawn: {exc}") from exc

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-20:]
        raise WolfDawnError(
            "cargo build --release failed for WolfDawn:\n" + "\n".join(tail)
        )

    built = _built_binary_path()
    if not built.is_file():
        raise WolfDawnError(
            f"cargo build reported success but {built} is missing. "
            "Check the WolfDawn workspace layout."
        )
    _log("WolfDawn 'wolf' binary ready", log_fn)
    return _persist_binary(built, log_fn)


def _log(msg: str, log_fn) -> None:
    if log_fn:
        log_fn(msg)


def _str(p: PathLike) -> str:
    return str(p)


def _run(args: Sequence[str], log_fn=None) -> WolfResult:
    """Run ``wolf <args...>`` and capture output. Ensures the binary exists first."""
    binary = ensure_wolf_binary(log_fn=log_fn)
    argv = [str(binary), *[str(a) for a in args]]
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    result = WolfResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        argv=argv,
    )
    if log_fn:
        for line in result.stderr.splitlines():
            log_fn(line)
    return result


# ---------------------------------------------------------------------------
# Command wrappers
# ---------------------------------------------------------------------------

def unpack_all(inputs: Union[PathLike, Iterable[PathLike]], out_dir: PathLike, log_fn=None) -> WolfResult:
    """``wolf unpack-all <data-dir|archive.wolf>... -o <out-dir>``.

    Each ``Name.wolf`` is unpacked to ``<out-dir>/Name/``.
    """
    if isinstance(inputs, (str, Path)):
        inputs = [inputs]
    args = ["unpack-all", *[_str(p) for p in inputs], "-o", _str(out_dir)]
    return _run(args, log_fn=log_fn)


def strings_extract(input_path: PathLike, out_json: PathLike, log_fn=None) -> WolfResult:
    """``wolf strings-extract <file|dir> -o <out.json>``.

    Accepts a map ``.mps``, ``CommonEvent.dat``, a ``.project`` database, ``Game.dat``,
    a single event-text ``.txt``, or a directory of ``.txt`` files.
    """
    return _run(["strings-extract", _str(input_path), "-o", _str(out_json)], log_fn=log_fn)


def names_extract(data_dir: PathLike, out_json: PathLike, log_fn=None) -> WolfResult:
    """``wolf names-extract <data-dir> -o <names.json>`` (project-wide name glossary)."""
    return _run(["names-extract", _str(data_dir), "-o", _str(out_json)], log_fn=log_fn)


def strings_inject(
    edited_json: PathLike,
    base: PathLike,
    output: PathLike,
    allow_code_drift: bool = False,
    en_punct: bool = False,
    log_fn=None,
) -> WolfResult:
    """``wolf strings-inject <edited.json> --base <orig> -o <out> [flags]``."""
    args = ["strings-inject", _str(edited_json), "--base", _str(base), "-o", _str(output)]
    if allow_code_drift:
        args.append("--allow-code-drift")
    if en_punct:
        args.append("--en-punct")
    return _run(args, log_fn=log_fn)


def names_inject(
    names_json: PathLike,
    data_dir: PathLike,
    out_dir: Optional[PathLike] = None,
    allow_code_drift: bool = False,
    en_punct: bool = False,
    log_fn=None,
) -> WolfResult:
    """``wolf names-inject <names.json> --data <data-dir> [-o <out-dir>] [flags]``."""
    args = ["names-inject", _str(names_json), "--data", _str(data_dir)]
    if out_dir is not None:
        args += ["-o", _str(out_dir)]
    if allow_code_drift:
        args.append("--allow-code-drift")
    if en_punct:
        args.append("--en-punct")
    return _run(args, log_fn=log_fn)


def names_check(json_files: Iterable[PathLike], log_fn=None) -> WolfResult:
    """``wolf names-check <file.json>...`` - report inconsistently translated names."""
    args = ["names-check", *[_str(p) for p in json_files]]
    return _run(args, log_fn=log_fn)


def pack(
    directory: PathLike,
    output: PathLike,
    like: Optional[PathLike] = None,
    encrypt: bool = False,
    version: Optional[str] = None,
    log_fn=None,
) -> WolfResult:
    """``wolf pack <dir> -o <out.wolf> [--like <orig> | --encrypt [--version <hex>]]``."""
    args = ["pack", _str(directory), "-o", _str(output)]
    if like is not None:
        args += ["--like", _str(like)]
    elif encrypt:
        args.append("--encrypt")
        if version:
            args += ["--version", str(version)]
    return _run(args, log_fn=log_fn)


def save_update(
    input_path: PathLike,
    output: Optional[PathLike] = None,
    title: Optional[str] = None,
    game: Optional[PathLike] = None,
    translations: Optional[Iterable[PathLike]] = None,
    log_fn=None,
) -> WolfResult:
    """``wolf save-update <save.sav|dir> [-o <out>] [--title <t> | --game <Game.dat>] [--translations ...]``."""
    args = ["save-update", _str(input_path)]
    if output is not None:
        args += ["-o", _str(output)]
    if title is not None:
        args += ["--title", title]
    elif game is not None:
        args += ["--game", _str(game)]
    if translations:
        args.append("--translations")
        args += [_str(p) for p in translations]
    return _run(args, log_fn=log_fn)
