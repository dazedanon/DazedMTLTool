"""WolfDawn CLI bootstrap and thin subprocess wrappers.

WolfDawn is the Rust toolchain (https://gitgud.io/zero64801/wolfdawn) that
unpacks, extracts, injects, and repacks WOLF RPG Editor game data. DazedMTLTool
ships prebuilt ``wolf`` binaries offline under ``util/wolfdawn/bin/<platform>/``
so end users never need a Rust toolchain or a live upstream fetch. Binaries are
updated when DazedMTLTool itself is updated. Everything the Wolf workflow needs
goes through the helpers here so command syntax and exit-code handling live in
one place.

Exit codes emitted by ``wolf`` (see WolfDawn crates/wolf-cli/src/main.rs):
    0   success
    2   round-trip mismatch / inject guard / name-consistency failure
    4   read / parse / write / crypto failure
    64  usage error (bad arguments / unknown subcommand)
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence, Union

__all__ = [
    "WolfDawnError",
    "WolfResult",
    "wolf_binary_path",
    "bundled_binary_path",
    "ensure_wolf_binary",
    "download_wolf_binary",
    "unpack_all",
    "strings_extract",
    "names_extract",
    "strings_inject",
    "names_inject",
    "parse_strings_inject_counts",
    "parse_strings_inject_untranslated",
    "parse_strings_inject_mismatches",
    "parse_names_inject_counts",
    "inject_had_applied",
    "pack",
    "save_update",
    "names_check",
    "relayout",
    "desc_relayout",
]

# strings-inject: "applied N translation(s) (M drifted)"; names-inject uses "name change(s)".
_INJECT_COUNTS_RE = re.compile(
    r"applied\s+(\d+)\s+translation.*?(\d+)\s+drifted", re.IGNORECASE | re.DOTALL
)
_INJECT_UNTRANSLATED_RE = re.compile(
    r"applied\s+\d+\s+translation.*?\((\d+)\s+untranslated", re.IGNORECASE | re.DOTALL
)
_INJECT_MISMATCH_RE = re.compile(
    r"^(?:event\s+\d+\s+)?cmd\s+(\d+)\s+str\s+(\d+):\s+control-code mismatch",
    re.IGNORECASE | re.MULTILINE,
)
_INJECT_MISMATCH_EVENT_RE = re.compile(
    r"^event\s+(\d+)\s+cmd\s+(\d+)\s+str\s+(\d+):\s+control-code mismatch",
    re.IGNORECASE | re.MULTILINE,
)
_NAMES_INJECT_COUNTS_RE = re.compile(
    r"applied\s+(\d+)\s+name change.*?(\d+)\s+drifted", re.IGNORECASE | re.DOTALL
)

ProgressFn = Callable[[int, int, str], None]

_UNPACK_ARCHIVE_DONE_RE = re.compile(
    r"^\s+(?P<name>\S+\.wolf)\s+->\s+(?P<dest>.+?)\s+\((?P<files>\d+) files\)\s*$"
)
_UNPACK_ONE_DONE_RE = re.compile(
    r"^unpacked\s+(?P<files>\d+)\s+files\s+->", re.IGNORECASE
)
_UNPACK_SUMMARY_RE = re.compile(
    r"^unpack-all:\s+(?P<archives>\d+) archive\(s\),\s+(?P<files>\d+) files\s*$"
)


def _inject_output_text(stdout: str, stderr: str) -> str:
    """WolfDawn prints per-line guards to stderr and the summary to either stream."""
    return "\n".join(part for part in (stdout or "", stderr or "") if part)


def parse_strings_inject_counts(stdout: str, stderr: str = "") -> tuple[int | None, int | None]:
    """Return (applied, drifted) from wolf strings-inject output, or (None, None)."""
    text = _inject_output_text(stdout, stderr)
    if not text:
        return None, None
    m = _INJECT_COUNTS_RE.search(text)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def parse_strings_inject_untranslated(stdout: str, stderr: str = "") -> int | None:
    """Return the untranslated line count from strings-inject summary, if present."""
    text = _inject_output_text(stdout, stderr)
    m = _INJECT_UNTRANSLATED_RE.search(text)
    return int(m.group(1)) if m else None


def parse_strings_inject_mismatches(stdout: str, stderr: str = "") -> list[str]:
    """Return human-readable control-code mismatch locations from inject output."""
    text = _inject_output_text(stdout, stderr)
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if "control-code mismatch" in line:
            out.append(line)
    return out


def parse_names_inject_counts(stdout: str, stderr: str = "") -> tuple[int | None, int | None]:
    """Return (applied, drifted) from wolf names-inject output, or (None, None)."""
    text = _inject_output_text(stdout, stderr)
    if not text:
        return None, None
    m = _NAMES_INJECT_COUNTS_RE.search(text)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def inject_had_applied(applied: int | None) -> bool:
    """True when WolfDawn reported at least one applied change.

    WolfDawn may exit 2 when a few lines fail safety guards but still writes the
    rest; treat a positive applied count as success for inject bookkeeping.
    """
    return applied is not None and applied > 0

# Committed, prebuilt binaries live here (per-platform) so end users don't need a
# Rust toolchain or a live upstream fetch.
_PACKAGE_DIR = Path(__file__).resolve().parent
_BUNDLED_DIR = _PACKAGE_DIR / "bin"

# WolfDawn upstream project on gitgud.io (a GitLab instance). The numeric project
# id is used for the uploads URL because the human-readable project path sits
# behind a Cloudflare challenge, while ``/-/project/<id>/uploads/...`` does not.
_GITGUD_HOST = "https://gitgud.io"
_WOLFDAWN_PROJECT_ID = 48753
_RELEASES_API = f"{_GITGUD_HOST}/api/v4/projects/{_WOLFDAWN_PROJECT_ID}/releases"
# Substring that identifies each platform's prebuilt zip in a release. Only the
# assets the upstream maintainer publishes can be pulled; unpublished platforms
# fall back to the committed offline binary.
_RELEASE_ASSET_MATCH = {
    "windows": "win",
    "linux": "linux",
    "macos": "mac",
}
_DOWNLOAD_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "DazedMTLTool WolfDawn-fetch"
)

PathLike = Union[str, Path]


class WolfDawnError(RuntimeError):
    """Raised when the WolfDawn binary can't be located/downloaded or a command fails hard."""


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


def _exe_name() -> str:
    return "wolf.exe" if sys.platform.startswith("win") else "wolf"


def _platform_dir() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def bundled_binary_path(platform: Optional[str] = None) -> Path:
    """Committed/cached prebuilt binary path for a platform (may not exist)."""
    platform = platform or _platform_dir()
    exe = "wolf.exe" if platform == "windows" else "wolf"
    return _BUNDLED_DIR / platform / exe


def wolf_binary_path() -> Path:
    """Preferred ``wolf`` binary path for the current platform (may not exist)."""
    return bundled_binary_path()


def _latest_release_asset(platform: str) -> Optional[tuple[str, str]]:
    """Return ``(tag_name, download_url)`` for the newest release with a platform zip."""
    match = _RELEASE_ASSET_MATCH.get(platform)
    if not match:
        return None
    req = urllib.request.Request(_RELEASES_API, headers={"User-Agent": _DOWNLOAD_UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        releases = json.loads(resp.read().decode("utf-8"))
    link_re = re.compile(r"\[([^\]]+)\]\((/uploads/[0-9a-f]+/[^)]+)\)")
    for release in releases:
        tag = release.get("tag_name") or ""
        description = release.get("description") or ""
        for filename, upload_path in link_re.findall(description):
            name = filename.lower()
            if match in name and name.endswith(".zip"):
                url = f"{_GITGUD_HOST}/-/project/{_WOLFDAWN_PROJECT_ID}{upload_path}"
                return tag, url
    return None


def _find_release_upload_url(platform: str) -> Optional[str]:
    """Look up the newest release and return the download URL of ``platform``'s zip.

    WolfDawn attaches prebuilt zips to a release as GitLab *uploads* referenced
    from the release description markdown, e.g.
    ``[WolfDawn-win64.zip](/uploads/<hash>/WolfDawn-win64.zip)``. Returns the
    numeric-project uploads URL (which bypasses the Cloudflare challenge) or
    ``None`` when the platform isn't published.
    """
    asset = _latest_release_asset(platform)
    return asset[1] if asset else None


def _extract_wolf_from_zip(zip_bytes: bytes, dest: Path, log_fn=None) -> Path:
    """Extract the ``wolf``/``wolf.exe`` member from a release zip into ``dest``."""
    want = dest.name.lower()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        member = None
        for info in zf.infolist():
            base = info.filename.rsplit("/", 1)[-1].lower()
            if base == want:
                member = info
                break
        if member is None:
            names = ", ".join(i.filename for i in zf.infolist())
            raise WolfDawnError(
                f"WolfDawn release zip did not contain '{dest.name}' (found: {names})."
            )
        payload = zf.read(member)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)
    try:
        dest.chmod(0o755)
    except OSError:  # pragma: no cover - non-POSIX filesystems
        pass
    _log(f"Saved WolfDawn binary to {dest}", log_fn)
    return dest


def download_wolf_binary(platform: Optional[str] = None, log_fn=print) -> Path:
    """Pull the prebuilt ``wolf`` binary from the WolfDawn release and cache it.

    Downloads the platform's release zip, extracts the ``wolf`` executable into
    ``util/wolfdawn/bin/<platform>/``, and returns its path. Raises
    :class:`WolfDawnError` when the platform has no published binary or the
    download fails.
    """
    platform = platform or _platform_dir()
    dest = bundled_binary_path(platform)
    _log(f"Looking up WolfDawn '{platform}' binary on {_GITGUD_HOST} ...", log_fn)
    try:
        url = _find_release_upload_url(platform)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise WolfDawnError(
            f"Could not reach the WolfDawn release page: {exc}. "
            f"Place a prebuilt binary at {dest} to work fully offline."
        ) from exc
    if not url:
        raise WolfDawnError(
            f"No prebuilt WolfDawn binary is published for '{platform}'. "
            f"Place one at {dest}, or build it from source "
            "(https://gitgud.io/zero64801/wolfdawn)."
        )
    _log(f"Downloading WolfDawn binary from {url} ...", log_fn)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _DOWNLOAD_UA})
        with urllib.request.urlopen(req, timeout=120) as resp:
            zip_bytes = resp.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise WolfDawnError(f"Failed to download WolfDawn binary: {exc}") from exc
    return _extract_wolf_from_zip(zip_bytes, dest, log_fn)


def _ensure_executable(path: Path) -> None:
    """Ensure a bundled binary is executable (git checkout may drop +x)."""
    if _platform_dir() == "windows":
        return
    try:
        if path.stat().st_mode & 0o111:
            return
        path.chmod(0o755)
    except OSError:  # pragma: no cover - non-POSIX filesystems
        pass


def ensure_wolf_binary(log_fn=print) -> Path:
    """Return the bundled ``wolf`` binary path (no upstream fetch at runtime).

    Raises :class:`WolfDawnError` when no offline binary is present for this
    platform. Maintainers refresh bundled binaries with
    ``python -m util.wolfdawn.update_tools --refresh-all``.
    """
    bundled = bundled_binary_path()
    if bundled.is_file():
        _ensure_executable(bundled)
        return bundled
    raise WolfDawnError(
        f"No bundled WolfDawn binary for '{_platform_dir()}' at {bundled}. "
        "Update DazedMTLTool to receive a prebuilt wolf binary."
    )


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


def _emit_unpack_progress(
    progress_fn: ProgressFn | None,
    current: int,
    total: int,
    label: str,
) -> None:
    if progress_fn:
        progress_fn(current, total, label)


def _run_streaming(
    args: Sequence[str],
    log_fn=None,
    progress_fn: ProgressFn | None = None,
    progress_total: int | None = None,
) -> WolfResult:
    """Run ``wolf`` and stream merged stdout/stderr line-by-line."""
    binary = ensure_wolf_binary(log_fn=log_fn)
    argv = [str(binary), *[str(a) for a in args]]
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    is_unpack = bool(args) and args[0] == "unpack-all"
    total = progress_total or 0
    current = 0

    if is_unpack and progress_fn and total > 0:
        _emit_unpack_progress(
            progress_fn,
            0,
            total,
            f"Unpacking archive 1 of {total} …",
        )

    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.rstrip("\r\n")
        stdout_lines.append(line)
        if log_fn:
            log_fn(line)
        if not is_unpack or not progress_fn:
            continue
        summary = _UNPACK_SUMMARY_RE.match(line)
        if summary:
            total = int(summary.group("archives"))
            continue
        match = _UNPACK_ARCHIVE_DONE_RE.match(line)
        if not match:
            continue
        current += 1
        if total <= 0:
            total = current
        name = match.group("name")
        files = match.group("files")
        if current < total:
            label = f"Unpacked {name} ({files} files) — archive {current + 1} of {total} …"
        else:
            label = f"Unpacked {name} ({files} files)"
        _emit_unpack_progress(progress_fn, current, total, label)

    returncode = proc.wait()
    stdout = "\n".join(stdout_lines)
    return WolfResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stdout,
        argv=argv,
    )


def count_unpack_archives(inputs: Union[PathLike, Iterable[PathLike]]) -> int | None:
    """Return how many ``.wolf`` archives *inputs* will unpack, or None if unknown."""
    expanded = _expand_wolf_archives(inputs)
    if expanded is None:
        return None
    return len(expanded)


def _expand_wolf_archives(inputs: Union[PathLike, Iterable[PathLike]]) -> list[Path] | None:
    """Expand directory inputs to ``*.wolf`` files; return None if any path is invalid."""
    if isinstance(inputs, (str, Path)):
        inputs = [inputs]
    archives: list[Path] = []
    for item in inputs:
        path = Path(item)
        if path.is_file():
            lower = path.name.lower()
            if lower.endswith(".wolf") or lower.endswith(".wolf.bak"):
                archives.append(path)
            else:
                return None
        elif path.is_dir():
            archives.extend(sorted(path.glob("*.wolf")))
        else:
            return None
    return archives


def _parse_unpack_one_files(stdout: str) -> str | None:
    for line in (stdout or "").splitlines():
        match = _UNPACK_ONE_DONE_RE.match(line.strip())
        if match:
            return match.group("files")
    return None

# ---------------------------------------------------------------------------
# Command wrappers
# ---------------------------------------------------------------------------

def unpack_all(
    inputs: Union[PathLike, Iterable[PathLike]],
    out_dir: PathLike,
    log_fn=None,
    progress_fn: ProgressFn | None = None,
    progress_total: int | None = None,
) -> WolfResult:
    """Unpack each ``Name.wolf`` to ``<out-dir>/Name/``.

    WolfDawn reads each archive entirely into memory (``std::fs::read``), so this
    runs ``wolf unpack`` once per archive in a fresh subprocess. That way peak
    RAM is freed between large archives instead of stacking in one long
    ``unpack-all`` process.
    """
    archives = _expand_wolf_archives(inputs)
    if archives is None:
        return WolfResult(
            returncode=64,
            stdout="",
            stderr="invalid unpack input path",
            argv=["wolf", "unpack", "…"],
        )
    if not archives:
        return WolfResult(
            returncode=4,
            stdout="",
            stderr="no .wolf archives found in the given paths",
            argv=["wolf", "unpack", "…"],
        )

    total = progress_total if progress_total is not None else len(archives)
    out_root = Path(out_dir)
    ok = 0
    failed = 0
    total_files = 0
    log_lines: list[str] = []
    last_argv: list[str] = []

    for index, archive in enumerate(archives):
        stem = archive.stem
        target = out_root / stem
        if progress_fn and total > 0:
            _emit_unpack_progress(
                progress_fn,
                index,
                total,
                f"Unpacking {archive.name} ({index + 1} of {total}) …",
            )
        res = _run(["unpack", _str(archive), "-o", _str(target)], log_fn=log_fn)
        last_argv = res.argv
        if res.stdout:
            log_lines.append(res.stdout.strip())
        if res.ok:
            ok += 1
            files = _parse_unpack_one_files(res.stdout) or "?"
            try:
                total_files += int(files)
            except ValueError:
                pass
            if progress_fn and total > 0:
                label = f"Unpacked {archive.name} ({files} files)"
                if index + 1 < total:
                    label += f" — archive {index + 2} of {total} …"
                _emit_unpack_progress(progress_fn, index + 1, total, label)
        else:
            failed += 1
            if log_fn:
                log_fn(f"  {archive.name} FAILED (exit {res.returncode})")

    summary = f"unpack-all: {ok} archive(s), {total_files} files"
    if failed:
        summary += f", {failed} failed"
    if log_fn:
        log_fn(summary)
    log_lines.append(summary)

    return WolfResult(
        returncode=0 if ok > 0 else 4,
        stdout="\n".join(log_lines),
        stderr="",
        argv=last_argv or ["wolf", "unpack", "…"],
    )


def unpack_one(
    archive: PathLike,
    out_dir: PathLike,
    log_fn=None,
) -> WolfResult:
    """``wolf unpack <archive.wolf> -o <out-dir>``."""
    return _run(["unpack", _str(archive), "-o", _str(out_dir)], log_fn=log_fn)


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


def relayout(
    data_dir: PathLike,
    out_dir: Optional[PathLike] = None,
    *,
    width: Optional[int] = None,
    width_face: Optional[int] = None,
    max_rows: Optional[int] = None,
    sub_width: Optional[int] = None,
    base_font: Optional[int] = None,
    no_formup: bool = False,
    no_resolve: bool = False,
    log_fn=None,
) -> WolfResult:
    """``wolf relayout <data-dir> [-o <out-dir>] [flags]``.

    Without ``-o`` this is a dry run. With ``-o``, only changed map / CommonEvent
    files are written under ``out_dir`` (paths relative to ``data_dir``).
    """
    args: list[str] = ["relayout", _str(data_dir)]
    if out_dir is not None:
        args += ["-o", _str(out_dir)]
    if width is not None:
        args += ["--width", str(int(width))]
    if width_face is not None:
        args += ["--width-face", str(int(width_face))]
    if max_rows is not None and int(max_rows) > 0:
        args += ["--max-rows", str(int(max_rows))]
    if sub_width is not None:
        args += ["--sub-width", str(int(sub_width))]
    if base_font is not None:
        args += ["--base-font", str(int(base_font))]
    if no_formup:
        args.append("--no-formup")
    if no_resolve:
        args.append("--no-resolve")
    return _run(args, log_fn=log_fn)


def desc_relayout(
    project: PathLike,
    output: PathLike,
    *,
    width: Optional[int] = None,
    max_lines: Optional[int] = None,
    font: Optional[int] = None,
    min_font: Optional[int] = None,
    types: Optional[str] = None,
    keep_breaks: bool = False,
    no_formup: bool = False,
    log_fn=None,
) -> WolfResult:
    """``wolf desc-relayout <X.project> -o <out.project> [flags]``.

    ``width`` may be omitted when ``wolfdawn-roles.json`` defines ``descBoxes``.
    ``max_lines=0`` means auto (read each field's ``[N行]`` hint).
    """
    args: list[str] = ["desc-relayout", _str(project), "-o", _str(output)]
    if width is not None:
        args += ["--width", str(int(width))]
    if max_lines is not None:
        args += ["--max-lines", str(int(max_lines))]
    if font is not None:
        args += ["--font", str(int(font))]
    if min_font is not None:
        args += ["--min-font", str(int(min_font))]
    if types:
        args += ["--types", str(types)]
    if keep_breaks:
        args.append("--keep-breaks")
    if no_formup:
        args.append("--no-formup")
    return _run(args, log_fn=log_fn)
