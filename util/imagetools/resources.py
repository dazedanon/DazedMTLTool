"""The parts of the semi-manual image workflow that are not in the repository.

Two kinds of thing are missing from a fresh checkout: Python packages nobody
else in DazedTL needs (numpy, OpenCV, an OCR client) and around 450 MB of
neural-network weights. Neither belongs in ``requirements.txt``, because
everyone who never opens this workflow would pay for both.

So nothing here is fetched until the user asks for it. ``gui/image_manager.py``
calls ``ensure_resources`` when the *Edit text…* button is pressed; that shows
what is missing and what it costs, and only then does anything leave the
network.

**This module must import on a bare checkout**, before any of it is installed,
because it is what does the installing. Standard library only - no numpy, no
cv2, no PyQt. The rest of ``util.imagetools`` is not importable until
``install`` has run, which is why nothing here imports its siblings.

Downloading works without a restart. New packages land in a ``site-packages``
that is already on ``sys.path``, so ``activate`` only has to drop the import
caches for the interpreter to see them - but that is only true because nothing
imported numpy or cv2 earlier in the session. Every route into the toolkit is a
deferred import inside a function for exactly this reason; a module-level
``import cv2`` anywhere in the always-loaded path would quietly reintroduce the
restart.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from util.paths import DATA_DIR

#: Where ``util.imagetools.inpaint`` looks. Repeated rather than imported
#: because that module needs numpy and cv2, which may be exactly what is
#: missing. ``ResourceManifestTests`` asserts the two agree.
MODEL_DIR = DATA_DIR / "models"
LIB_DIR = DATA_DIR / "libs"

USER_AGENT = "DazedTL"
#: Big enough that the syscall overhead disappears on a 200 MB model, small
#: enough that a progress bar still moves smoothly.
CHUNK = 256 * 1024
TIMEOUT = 60

HUGGINGFACE = "https://huggingface.co/{repo}/resolve/main/{filename}"
PATCHMATCH_RELEASE = (
    "https://github.com/dmMaze/PyPatchMatchInpaint/releases/download/v1.0/{asset}"
)

#: Rough wheel sizes, only ever used to fill in the "about this much" line
#: before anything is downloaded. The progress bars use ``Content-Length``.
PIP_SIZES = {
    "numpy": 16_000_000,
    "opencv-python-headless": 40_000_000,
    "chrome-lens-py": 12_000_000,
    "onnxruntime": 16_000_000,
    "py7zr": 3_000_000,
    "rapidocr-onnxruntime": 15_000_000,
}


class Cancelled(Exception):
    """The user stopped the download."""


@dataclass(frozen=True)
class Resource:
    """One thing that can be fetched, and how to tell whether it is here."""

    key: str
    label: str
    detail: str
    #: Requirement specifiers handed to pip.
    pips: tuple[str, ...] = ()
    #: Import names that prove the pips landed. Checked with ``find_spec``,
    #: which does not execute them - importing numpy here would defeat the
    #: whole deferred-import arrangement.
    modules: tuple[str, ...] = ()
    #: A file to download, or the directory an archive unpacks into.
    url: str = ""
    dest: Path | None = None
    size: int = 0
    #: Set when ``url`` points at an archive rather than the file itself.
    archive: bool = False
    #: Filenames under ``dest`` any one of which proves an archive unpacked.
    proof: tuple[str, ...] = ()
    #: Pre-ticked in the download prompt.
    default: bool = False
    #: The workflow cannot start without it, so it cannot be unticked.
    required: bool = False
    #: ``sys.platform`` values this is published for; empty means all.
    platforms: tuple[str, ...] = ()


def _patchmatch_asset() -> str:
    """The release asset for this machine, or "" where none is published.

    Only Windows and Apple Silicon builds exist. There is no Linux build at
    all, so the row is hidden there rather than offered and then failing.
    """
    if sys.platform == "win32":
        return "windows_patchmatch_libs.7z"
    if sys.platform == "darwin" and _is_arm():
        return "macos_arm64_patchmatch_libs.7z"
    return ""


def _is_arm() -> bool:
    import platform

    return platform.machine().lower() in {"arm64", "aarch64"}


RESOURCES: tuple[Resource, ...] = (
    Resource(
        key="core",
        label="Required",
        detail="numpy, OpenCV and the Google Lens OCR client",
        pips=("numpy>=2.0", "opencv-python-headless>=4.10", "chrome-lens-py>=3.4"),
        modules=("numpy", "cv2", "chrome_lens_py"),
        default=True,
        required=True,
    ),
    Resource(
        key="aot",
        label="AOT reconstruction",
        detail="fast neural fill; weaker on saturated colour",
        pips=("onnxruntime>=1.17",),
        modules=("onnxruntime",),
        url=HUGGINGFACE.format(repo="ogkalu/aot-inpainting", filename="aot.onnx"),
        dest=MODEL_DIR / "aot.onnx",
        size=23_068_213,
        default=True,
    ),
    Resource(
        key="lama_manga",
        label="LaMa-manga reconstruction",
        detail="LaMa fine-tuned on manga and anime - the best of these on game art",
        pips=("onnxruntime>=1.17",),
        modules=("onnxruntime",),
        url=HUGGINGFACE.format(
            repo="ogkalu/lama-manga-onnx-dynamic",
            filename="lama-manga-dynamic.onnx",
        ),
        dest=MODEL_DIR / "lama-manga-dynamic.onnx",
        size=206_291_843,
    ),
    Resource(
        key="lama",
        label="LaMa reconstruction",
        detail="the original LaMa export, trained on photographs",
        pips=("onnxruntime>=1.17",),
        modules=("onnxruntime",),
        url=HUGGINGFACE.format(repo="Carve/LaMa-ONNX", filename="lama_fp32.onnx"),
        dest=MODEL_DIR / "lama_fp32.onnx",
        size=208_044_816,
    ),
    Resource(
        key="patchmatch",
        label="PatchMatch reconstruction",
        detail="best texture of the six, and by far the slowest (~4.5s a box)",
        pips=("py7zr>=0.21",),
        modules=("py7zr",),
        url=PATCHMATCH_RELEASE.format(asset=_patchmatch_asset() or "unavailable"),
        dest=LIB_DIR,
        size=12_385_730,
        archive=True,
        proof=(
            "patchmatch_inpaint.dll",
            "libpatchmatch_inpaint.so",
            "libpatchmatch_inpaint.dylib",
            "patchmatch_inpaint.dylib",
        ),
        platforms=("win32", "darwin"),
    ),
    Resource(
        key="rapidocr",
        label="Offline OCR",
        detail=(
            "a local fallback for when the Google Lens endpoint is unreachable "
            "(also pulls in the full opencv-python)"
        ),
        # The maintained successor to rapidocr-onnxruntime, which caps out at
        # Python 3.12 - asking for the old name on 3.13 silently resolves to a
        # three-year-old release. util/imagetools/ocr/rapid.py accepts either,
        # so an existing install of the old one keeps working.
        pips=("rapidocr",),
        modules=("rapidocr",),
        size=0,
    ),
)


# ----------------------------------------------------------------- inspection

def available() -> tuple[Resource, ...]:
    """The resources that can be fetched on this machine."""
    rows = []
    for resource in RESOURCES:
        if resource.platforms and sys.platform not in resource.platforms:
            continue
        if resource.key == "patchmatch" and not _patchmatch_asset():
            continue
        rows.append(resource)
    return tuple(rows)


def get(key: str) -> Resource:
    for resource in RESOURCES:
        if resource.key == key:
            return resource
    raise KeyError(f"No image-workflow resource named {key!r}")


def _importable(module: str) -> bool:
    from importlib.util import find_spec

    try:
        return find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def installed(resource: Resource | str) -> bool:
    """Whether everything this resource brings is already present."""
    if isinstance(resource, str):
        resource = get(resource)
    if not all(_importable(module) for module in resource.modules):
        return False
    if resource.dest is None:
        return True
    if resource.archive:
        return any((resource.dest / name).is_file() for name in resource.proof)
    return resource.dest.is_file()


def missing(keys: list[str] | tuple[str, ...] | None = None) -> list[Resource]:
    """Selected resources that are not fully present, in manifest order."""
    wanted = available() if keys is None else [get(key) for key in keys]
    return [resource for resource in wanted if not installed(resource)]


def ready() -> bool:
    """Whether the workflow can start at all."""
    return all(installed(r) for r in available() if r.required)


def defaults() -> list[str]:
    """The keys pre-ticked in the prompt: required, plus the cheap ones."""
    return [r.key for r in available() if r.default]


def _requirement_name(spec: str) -> str:
    for separator in (">=", "==", "<=", "~=", ">", "<", "!=", "["):
        if separator in spec:
            return spec.split(separator, 1)[0].strip()
    return spec.strip()


def estimate(resources) -> int:
    """Bytes the given resources will roughly cost, counting pips once."""
    total = 0
    seen: set[str] = set()
    for resource in resources:
        if resource.dest is not None and not installed(resource):
            total += resource.size
        for spec in resource.pips:
            name = _requirement_name(spec)
            if name in seen:
                continue
            seen.add(name)
            if not all(_importable(m) for m in resource.modules):
                total += PIP_SIZES.get(name, 0)
    return total


def human(size: int) -> str:
    if size >= 1_000_000_000:
        return f"{size / 1_000_000_000:.1f} GB"
    if size >= 1_000_000:
        return f"{size / 1_000_000:.0f} MB"
    if size >= 1_000:
        return f"{size / 1_000:.0f} KB"
    return f"{size} bytes"


# -------------------------------------------------------------- installation

def _log(log, message: str) -> None:
    if log is None:
        print(message, flush=True)
    else:
        log(message)


def _check(should_stop) -> None:
    if should_stop is not None and should_stop():
        raise Cancelled("Download stopped.")


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _pip(specs, log=None, should_stop=None) -> None:
    """Install requirement specifiers into *this* interpreter.

    ``sys.executable -m pip``, never bare ``pip``: the ``Scripts\\*.exe`` shims
    hardcode the interpreter they were built against, so in a virtualenv that
    was copied rather than created in place, bare ``pip`` installs into
    whichever tree the copy came from and the caller then reports the package
    as missing forever.
    """
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        *specs,
    ]
    _log(log, "$ " + " ".join(command))
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_no_window(),
    )
    try:
        for line in process.stdout or ():
            line = line.rstrip()
            if line:
                _log(log, line)
            if should_stop is not None and should_stop():
                process.terminate()
                raise Cancelled("Download stopped.")
    finally:
        code = process.wait()
    if code:
        raise RuntimeError(
            f"pip exited {code}. The lines above say why; a proxy or a missing "
            "wheel for this Python version are the usual causes."
        )


def _fetch(url: str, dest: Path, progress=None, log=None, should_stop=None) -> None:
    """Download to ``<dest>.part``, then rename.

    The rename is the only thing that publishes the file, so an interrupted
    download can never be mistaken for a complete one - which for a 200 MB
    model would surface much later as an unreadable ONNX graph.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    _log(log, f"Downloading {dest.name}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with open(part, "wb") as handle:
                while True:
                    _check(should_stop)
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total)
        if total and done != total:
            raise OSError(
                f"{dest.name} stopped short: {done} of {total} bytes. "
                "Nothing was kept."
            )
        part.replace(dest)
        _log(log, f"{dest.name} ready ({human(done)})")
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def _unpack(archive: Path, into: Path, log=None) -> None:
    """Flatten an archive into *into*.

    Flattened on purpose: the library loader looks in one directory, and the
    published archives nest their payload differently per platform. Extraction
    goes to a staging folder first and only plain files are moved across by
    basename, so nothing an archive claims about its own paths can write
    outside the destination.
    """
    import py7zr

    staging = into.parent / f"{into.name}.unpack"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with py7zr.SevenZipFile(archive, "r") as bundle:
            bundle.extractall(path=staging)
        into.mkdir(parents=True, exist_ok=True)
        moved = 0
        root = staging.resolve()
        for path in staging.rglob("*"):
            if not path.is_file():
                continue
            if root not in path.resolve().parents:
                continue
            shutil.move(str(path), str(into / path.name))
            moved += 1
        _log(log, f"Unpacked {moved} file(s) into {into}")
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def activate() -> None:
    """Make freshly installed packages importable without a restart."""
    import importlib
    import site

    candidates: list[str] = []
    try:
        candidates.extend(site.getsitepackages())
    except AttributeError:  # a virtualenv old enough to lack it
        pass
    try:
        user = site.getusersitepackages()
    except Exception:
        user = None
    if user:
        candidates.append(user)
    for path in candidates:
        if path and path not in sys.path:
            sys.path.append(path)
    importlib.invalidate_caches()


def install(resources, progress=None, log=None, should_stop=None) -> None:
    """Fetch everything in *resources*, in order.

    ``progress(key, done, total)`` is called as bytes arrive, with ``total``
    zero while a step has no measurable length (pip does not report one).
    Raises on the first failure - a half-installed set is reported honestly
    rather than papered over, and every step is safe to run again.
    """
    handled: set[str] = set()
    for resource in resources:
        _check(should_stop)
        if progress is not None:
            progress(resource.key, 0, 0)

        specs = [
            spec
            for spec in resource.pips
            if _requirement_name(spec) not in handled
        ]
        if specs and not all(_importable(m) for m in resource.modules):
            _log(log, f"- {resource.label}: installing {', '.join(specs)}")
            _pip(specs, log=log, should_stop=should_stop)
            activate()
        for spec in resource.pips:
            handled.add(_requirement_name(spec))

        if resource.dest is None:
            continue
        if installed(resource):
            _log(log, f"- {resource.label}: already here")
            continue

        _check(should_stop)
        if resource.archive:
            if not _patchmatch_asset() and resource.key == "patchmatch":
                raise RuntimeError(
                    "No PatchMatch build is published for this platform."
                )
            # Downloaded outside the library folder so a failed unpack cannot
            # leave an archive sitting where the loader goes looking.
            staging = DATA_DIR / f"_{resource.key}.archive"
            _fetch(
                resource.url,
                staging,
                progress=lambda done, total, key=resource.key: (
                    progress(key, done, total) if progress else None
                ),
                log=log,
                should_stop=should_stop,
            )
            try:
                _unpack(staging, resource.dest, log=log)
            finally:
                staging.unlink(missing_ok=True)
        else:
            _fetch(
                resource.url,
                resource.dest,
                progress=lambda done, total, key=resource.key: (
                    progress(key, done, total) if progress else None
                ),
                log=log,
                should_stop=should_stop,
            )

    activate()


# ----------------------------------------------------------------------- CLI

def _report(log=print) -> None:
    log("Semi-manual image workflow - extra resources\n")
    for resource in available():
        mark = "installed" if installed(resource) else "missing"
        size = human(estimate([resource])) if not installed(resource) else "-"
        log(f"  {resource.key:<12} {mark:<10} {size:>8}   {resource.label}")
        log(f"  {'':<12} {resource.detail}")
    log("")
    log(f"  Workflow can start: {'yes' if ready() else 'no'}")


def main(argv: list[str] | None = None) -> int:
    # pip's output is not ASCII and this console may not be UTF-8 - a Japanese
    # Windows console is cp932, where one stray character in a wheel's name
    # would otherwise end the install with a UnicodeEncodeError.
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    argv = list(sys.argv[1:] if argv is None else argv)
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        print(
            "Usage: python -m util.imagetools.resources "
            "[--all | --default | KEY ...]"
        )
        return 0

    if "--all" in argv:
        chosen = list(available())
    elif "--default" in argv:
        chosen = [r for r in available() if r.default]
    else:
        keys = [arg for arg in argv if not arg.startswith("-")]
        if not keys:
            _report()
            return 0
        try:
            chosen = [get(key) for key in keys]
        except KeyError as exc:
            print(exc)
            return 1

    wanted = [r for r in chosen if not installed(r)]
    if not wanted:
        print("Everything asked for is already installed.")
        return 0

    print(f"About {human(estimate(wanted))} to download:")
    for resource in wanted:
        print(f"  - {resource.label}")
    print()

    last = [-1]

    def progress(key: str, done: int, total: int) -> None:
        if not total:
            return
        percent = done * 100 // total
        if percent != last[0]:
            last[0] = percent
            print(f"\r  {key}: {percent}%", end="", flush=True)
            if percent == 100:
                print()

    try:
        install(wanted, progress=progress, log=print)
    except Cancelled:
        print("\nStopped.")
        return 1
    except Exception as exc:
        print(f"\nFailed: {type(exc).__name__}: {exc}")
        return 1
    print("\nDone. DazedTL does not need restarting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
