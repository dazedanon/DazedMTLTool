"""Putting the artwork back where the source text was.

`style.py` decides *what* to erase and `render.py` decides *how*; this decides
what fills the hole when the answer is "reconstruct it". Six methods, in three
families:

* **Telea** and **Navier-Stokes** ship with OpenCV, cost nothing, and diffuse
  the surrounding colour inwards. They are honest on flat backgrounds and they
  smear on anything with a pattern in it.
* **PatchMatch** copies real patches from elsewhere in the picture instead of
  averaging, so screentone and hatching survive it. It is not a model - no
  weights, no runtime - but it does need a small prebuilt library.
* **LaMa**, **LaMa (manga)** and **AOT** are networks. They are the only ones
  that will invent plausible *structure* across a hole rather than blur over it.

Everything past the first family is optional in the same way the RapidOCR
fallback is: unavailable announces itself with the reason and the fix, and the
rest of the tool carries on without it. Nothing is ever downloaded
automatically - the files are the user's to place.

Two things about this job are specific to game art and are easy to get wrong.

**Alpha is a channel, not a flag.** A name plate is routinely drawn as opaque
white glyphs cut into a 70% black bar. Reconstruct only the three colour
channels and the glyphs' *opacity* survives untouched: a perfect silhouette of
the Japanese, fully opaque inside a translucent bar, which shows up over the
game background as a hard black shadow of the text that was supposed to be
gone. So alpha is reconstructed alongside colour, always, whichever method
filled the colour - and always classically, because none of these models has
ever seen an alpha channel.

**Transparent pixels have no colour to lend.** The RGB under alpha 0 is
whatever the exporter left there, usually black. A reconstruction that treats
those as context walks that black inwards and darkens the repair. They are
therefore added to the mask - marked unknown rather than believed - and what
comes back for them is discarded, since their alpha keeps them invisible.
"""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from util.paths import DATA_DIR

TELEA = "telea"
NS = "ns"
PATCHMATCH = "patchmatch"
LAMA = "lama"
LAMA_MANGA = "lama_manga"
AOT = "aot"


class InpaintError(RuntimeError):
    """A specifically requested reconstruction backend could not be used."""


# Ordered cheapest-first, which is also least-surprising-first: this is the
# order they appear in the "Inpainting model" list.
METHODS = (TELEA, NS, PATCHMATCH, LAMA, LAMA_MANGA, AOT)

#: The two that need nothing installed.
CLASSICAL = (TELEA, NS)

METHOD_LABELS = {
    TELEA: "Fast — walk inwards from the edges",
    NS: "Fast — follow the lines through",
    PATCHMATCH: "PatchMatch — copy real patches from nearby",
    LAMA: "LaMa — a model that invents the missing texture",
    LAMA_MANGA: "LaMa (manga) — the same model, taught on comic art",
    AOT: "AOT — a lighter model, tuned for speech bubbles",
}

#: The same methods at note length: the render note says which reconstruction
#: actually ran, and the label's explanatory half would drown the sentence it
#: sits in. The two classical fills need distinct names here precisely because
#: their long labels both open with "Fast".
SHORT_NAMES = {
    TELEA: "Telea",
    NS: "Navier–Stokes",
    PATCHMATCH: "PatchMatch",
    LAMA: "LaMa",
    LAMA_MANGA: "LaMa (manga)",
    AOT: "AOT",
}


def short_label(method: str) -> str:
    """The method's name at in-a-sentence length."""
    return SHORT_NAMES.get(method, method or DEFAULT)

#: The one that always works. Nothing to install, nothing to download.
DEFAULT = TELEA

#: What to reach for first when it is there. AOT is the lightest of the three
#: models - a few seconds a block against LaMa's minute, and 23 MB against
#: 200 - and it is the one the downloader pre-ticks, so on most installs this
#: is the method the user already paid for. It only wins the default when it is
#: genuinely ready: ``preferred`` probes before choosing, never after.
PREFERRED = AOT

RADIUS = 3

# How much of the picture around the block the context-hungry methods are
# shown, as a multiple of the block's own size. Telea and Navier-Stokes
# deliberately get none of this: they average their way inwards from the mask
# edge, and a wider crop only gives them somewhere further away to average
# from. Everything else is the opposite - a model has nothing to say about a
# hole with no picture around it, and PatchMatch has nothing to copy.
CONTEXT = 1.0

#: Past this share of the tight crop being unknown, a diffusion fill has
#: nothing left in the crop to diffuse *from*. At exactly 1.0 `cv2.inpaint`
#: returns the crop untouched and reports no error, which reaches the user as
#: "reconstructed" over a block where the Japanese is still sitting there - and
#: text that fills its own box is not unusual, it is what a tight box around a
#: word looks like. Measured on the real assets: the fullest crop that still
#: worked was 97.4%, and the one that silently did nothing was 100%.
CROWDED = 0.90

#: How much context a crowded crop is given, as a multiple of its own size.
#: Deliberately less than `CONTEXT`: the aim is to put *some* picture back in
#: the frame, not to hand a diffusion fill somewhere distant to average from.
CROWDED_CONTEXT = 0.5

MODEL_DIR = DATA_DIR / "models"
LIB_DIR = DATA_DIR / "libs"

SCALE_UNIT = "01"       # the picture arrives as 0..1
SCALE_SIGNED = "-11"    # ...or as -1..1


@dataclass(frozen=True)
class Model:
    """One ONNX graph, and the conventions it expects.

    None of this is discoverable from the file, and every field here was
    settled by measurement rather than by reading someone's inference script:
    feed a graph a picture it understands and the region *outside* the mask
    comes back as very nearly what went in, so the right convention is the one
    that reproduces the surroundings.
    """

    filename: str
    source: str
    scale: str
    #: Whether the masked region must be zeroed before inference. The two LaMa
    #: exports do this inside the graph and are indifferent; AOT is not, and
    #: leaving its hole full of the original text lets it copy the text back.
    zero_hole: bool
    #: Longest side handed to the graph. Past this the picture is scaled down
    #: and the answer scaled back up - these networks were trained around
    #: 512px and get both slower and vaguer well before they get better.
    limit: int = 1024
    #: Shortest side handed to the graph. Below this AOT fails outright: it
    #: reduces by four and then reflect-pads the feature map by sixteen, so a
    #: crop under about 68px asks for a pad wider than the thing being padded
    #: and onnxruntime refuses the graph. Small blocks are common - a two-word
    #: label is smaller than this - so the crop is padded up to here rather
    #: than scaled up, which keeps the glyphs at their own resolution.
    minimum: int = 128


MODELS = {
    LAMA: Model(
        "lama_fp32.onnx",
        "https://huggingface.co/Carve/LaMa-ONNX",
        SCALE_UNIT,
        zero_hole=False,
    ),
    LAMA_MANGA: Model(
        "lama-manga-dynamic.onnx",
        "https://huggingface.co/ogkalu/lama-manga-onnx-dynamic",
        SCALE_UNIT,
        zero_hole=False,
    ),
    AOT: Model(
        "aot.onnx",
        "https://huggingface.co/ogkalu/aot-inpainting",
        SCALE_SIGNED,
        zero_hole=True,
    ),
}

#: Prebuilt PatchMatch libraries, from
#: https://github.com/dmMaze/PyPatchMatchInpaint/releases - unpack the archive
#: for this platform into ``data/libs``. The Windows one brings its own
#: ``opencv_world455.dll``, which has to sit in the same folder.
PATCHMATCH_SOURCE = "https://github.com/dmMaze/PyPatchMatchInpaint/releases"
PATCHMATCH_NAMES = (
    "patchmatch_inpaint.dll",
    "libpatchmatch_inpaint.so",
    "libpatchmatch_inpaint.dylib",
    "patchmatch_inpaint.dylib",
)
#: Patch size for PatchMatch. The reference default, and it holds up: smaller
#: reproduces noise, larger starts transplanting recognisable pieces of the
#: picture into the hole.
PATCH_SIZE = 15

LIB_ENV = "IMGTL_PATCHMATCH_LIBS"


def model_env(method: str) -> str:
    """Environment variable that overrides where *method*'s weights live."""
    return f"IMGTL_{method.upper()}_MODEL"


#: Kept as a name of its own because it is the oldest of these and the one
#: written down in requirements.txt.
MODEL_ENV = model_env(LAMA)


def model_path(method: str = LAMA) -> Path:
    """Where *method*'s weights are looked for."""
    override = os.environ.get(model_env(method), "").strip()
    if override:
        return Path(override)
    spec = MODELS.get(method)
    return MODEL_DIR / (spec.filename if spec else f"{method}.onnx")


def library_dir() -> Path:
    """Where the PatchMatch library is looked for."""
    override = os.environ.get(LIB_ENV, "").strip()
    return Path(override) if override else LIB_DIR


def library_path() -> Path | None:
    """The PatchMatch library on this machine, or None if it is not there."""
    directory = library_dir()
    for name in PATCHMATCH_NAMES:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def needs_context(method: str) -> bool:
    """Whether this method wants to see the picture around the hole."""
    return method not in CLASSICAL


# ------------------------------------------------------------- availability


def _probe_runtime() -> tuple[bool, str]:
    """Is onnxruntime importable *here*, and if not, why exactly?

    Every branch below names the interpreter. Two of these failures look
    identical from the outside and have opposite fixes - a package genuinely
    absent, and a package present in one Python while the application is
    running under another - and without the path there is no way to tell them
    apart from the panel.
    """
    import importlib

    importlib.invalidate_caches()
    where = f"(python: {sys.executable})"
    try:
        importlib.import_module("onnxruntime")
    except ModuleNotFoundError as exc:
        if exc.name == "onnxruntime":
            return False, (
                f"onnxruntime is not installed in this Python {where} — "
                "reopen this editor and accept the download, or run "
                "“python -m util.imagetools.resources --default”"
            )
        # The package is there but something inside it is not. This is a
        # ModuleNotFoundError too, and calling it "not installed" sends the
        # reader off to reinstall a package they can plainly see on disk.
        return False, (
            f"onnxruntime is installed but will not load {where}: no module "
            f"named “{exc.name}”. Usually a half-finished or mismatched "
            "install — pip install --force-reinstall onnxruntime"
        )
    except ImportError as exc:
        # Almost always the Visual C++ runtime: PyQt5 ships an older copy and
        # claims the name first if it is allowed to load before this. Say so,
        # because the message Windows gives names nothing at all.
        return False, (
            f"onnxruntime will not load {where}: {exc} — on Windows this is "
            "usually Qt's older Visual C++ runtime winning the race; see "
            "util/msvc_runtime.py"
        )
    except Exception as exc:
        return False, (
            f"onnxruntime will not load {where}: {type(exc).__name__}: {exc}"
        )
    return True, ""


#: How anything missing is obtained. Everything here is downloaded on demand
#: rather than shipped, so the useful half of "this is unavailable" is where to
#: get it - and that is one command, not a hunt through a release page.
GET = "python -m util.imagetools.resources"


def _probe(method: str) -> tuple[bool, str]:
    if method in CLASSICAL:
        return True, "ready (OpenCV, no download)"

    if method == PATCHMATCH:
        path = library_path()
        if path is None:
            return False, (
                f"no PatchMatch library in {library_dir()} — reopen this editor "
                f"and accept the download, or run “{GET} patchmatch”. To use a "
                f"copy from {PATCHMATCH_SOURCE} that you unpacked yourself, "
                f"point {LIB_ENV} at it"
            )
        try:
            _patchmatch()
        except Exception as exc:
            return False, f"the PatchMatch library will not load: {exc}"
        return True, f"ready ({path.name})"

    if method not in MODELS:
        return False, f"unknown method “{method}”"

    ok, detail = _probe_runtime()
    if not ok:
        return False, detail
    path = model_path(method)
    if not path.is_file():
        spec = MODELS[method]
        return False, (
            f"no model at {path} — reopen this editor and tick “{method}”, or "
            f"run “{GET} {method}”. To use a copy of {spec.filename} you "
            f"already have (from {spec.source}), point {model_env(method)} at it"
        )
    return True, f"ready ({path.name}, onnxruntime)"


def available(method: str) -> bool:
    return _probe(method)[0]


#: Memoised because ``preferred`` is asked once per block per render and the
#: answer costs an ``import onnxruntime``. ``forget`` clears it, which is what
#: makes a download inside a running session take effect.
_PREFERRED: dict[str, str] = {}


def preferred() -> str:
    """Which reconstruction a block gets when nobody has chosen one.

    ``DEFAULT`` for a fresh checkout, ``PREFERRED`` once the model is on disk
    and onnxruntime will load it. Deliberately a probe rather than a constant:
    naming a model as *the* default would put every block that never opened the
    panel onto a method that is not installed, and the complaint would arrive at
    render time on somebody who chose nothing.
    """
    if "method" not in _PREFERRED:
        _PREFERRED["method"] = PREFERRED if available(PREFERRED) else DEFAULT
    return _PREFERRED["method"]


#: Past this many pixels on a block's *shorter* side, AOT stops being the right
#: first reach. Measured, not asserted: on the profile-screen test image a
#: 259x441 block came back from AOT as a dark blob with the erased text
#: embossed into it, and its small siblings came back hatched with the
#: screentone it was trained on; the same holes through LaMa kept the figure's
#: silhouette and colours. AOT keeps the default below the line because
#: bubble-sized holes are its home ground and it is several times quicker.
BIG_SIDE = 160


def preferred_for(width: int = 0, height: int = 0) -> str:
    """``preferred()``, but sized: LaMa for blocks past ``BIG_SIDE``.

    The panel calls this with the block it is describing and the renderer with
    the block it is filling, so the two always name the same method. Probed and
    memoised the same way as ``preferred`` - a model only wins while it is
    genuinely ready, and ``forget`` clears the answer.
    """
    if min(width, height) < BIG_SIDE:
        return preferred()
    if "large" not in _PREFERRED:
        _PREFERRED["large"] = next(
            (m for m in (LAMA, LAMA_MANGA) if available(m)), ""
        )
    return _PREFERRED["large"] or preferred()


def status(method: str) -> str:
    return f"{method}: {_probe(method)[1]}"


# ------------------------------------------------------------------- filling


def _classical(image: np.ndarray, mask: np.ndarray, flag: int, radius: int) -> np.ndarray:
    return cv2.inpaint(
        np.ascontiguousarray(image), np.ascontiguousarray(mask), radius, flag
    )


def fill_alpha(alpha: np.ndarray, mask: np.ndarray, radius: int = RADIUS) -> np.ndarray:
    """Reconstruct the *opacity* under the mask.

    Always classical, whichever method filled the colour: none of these models
    has an alpha channel in its training data, and the answer wanted here is
    nearly always "whatever the surface around the hole is", which is precisely
    what walking inwards from the edge produces.
    """
    if not mask.any():
        return alpha
    return _classical(alpha, mask.astype(np.uint8), cv2.INPAINT_TELEA, radius)


def fill(
    rgb: np.ndarray,
    mask: np.ndarray,
    method: str = DEFAULT,
    radius: int = RADIUS,
    *,
    allow_fallback: bool = True,
) -> tuple[np.ndarray, str]:
    """Reconstruct colour under the mask. Returns ``(pixels, complaint)``.

    The complaint is empty when the method asked for is the method that ran. It
    is a sentence when it is not - anything that failed to load says so and the
    picture still comes back repaired, because a fallback the user is told about
    is better than either a crash or a silent downgrade. Callers comparing model
    quality can pass ``allow_fallback=False`` so an unavailable or failed model
    raises :class:`InpaintError` instead of contaminating that comparison with a
    result from Telea.
    """
    solid = mask.astype(np.uint8)
    if not solid.any():
        return rgb, ""
    if method == NS:
        return _classical(rgb, solid, cv2.INPAINT_NS, radius), ""
    if method in (TELEA, "") or method not in METHODS:
        return _classical(rgb, solid, cv2.INPAINT_TELEA, radius), ""

    ok, detail = _probe(method)
    if not ok:
        complaint = (
            f"{_name(method)} is not available ({detail}), so this was "
            "reconstructed the fast way"
        )
        if not allow_fallback:
            raise InpaintError(complaint)
        return _classical(rgb, solid, cv2.INPAINT_TELEA, radius), complaint
    try:
        if method == PATCHMATCH:
            repaired = _patchmatch_fill(rgb, solid)
        else:
            repaired = _model_fill(method, rgb, solid)
    except Exception as exc:
        complaint = (
            f"{_name(method)} failed ({exc}), so this was reconstructed the fast way"
        )
        if not allow_fallback:
            raise InpaintError(complaint) from exc
        return _classical(rgb, solid, cv2.INPAINT_TELEA, radius), complaint
    # Only the hole is taken from the repair. Everywhere else the original
    # pixels are already right, and a model asked to reproduce them comes back
    # a shade off across the whole crop - which is a visible seam along the
    # edge of every block. The LaMa exports composite internally and do not
    # need this; AOT and PatchMatch very much do.
    return np.where(mask[:, :, None] > 0, repaired, rgb), ""


def reconstruct_rgba(
    rgba: np.ndarray,
    mask: np.ndarray,
    method: str = DEFAULT,
    *,
    allow_fallback: bool = True,
) -> tuple[np.ndarray, str, int]:
    """Reconstruct masked RGBA pixels and leave everything else exact.

    The caller chooses the contextual crop. Fully transparent pixels inside it
    are not trusted as colour context, while only the requested hole is copied
    back. Alpha is reconstructed separately because the RGB models do not know
    about it. Returns ``(pixels, complaint, changed_mask_pixels)``.
    """
    if rgba.ndim != 3 or rgba.shape[2] != 4 or rgba.dtype != np.uint8:
        raise ValueError("rgba must be an HxWx4 uint8 array")
    if mask.shape != rgba.shape[:2]:
        raise ValueError("mask dimensions must match the RGBA image")

    hole = mask.astype(bool)
    if not hole.any():
        return rgba.copy(), "", 0

    original = np.ascontiguousarray(rgba)
    result = original.copy()
    unknown = hole | (original[:, :, 3] == 0)
    rgb = cv2.cvtColor(original, cv2.COLOR_RGBA2RGB)
    repaired, complaint = fill(
        rgb, unknown, method, allow_fallback=allow_fallback
    )
    result[:, :, :3] = np.where(hole[:, :, None], repaired, original[:, :, :3])
    result[:, :, 3] = np.where(
        hole,
        fill_alpha(np.ascontiguousarray(original[:, :, 3]), hole),
        original[:, :, 3],
    )
    changed = int(((result != original).any(axis=2) & hole).sum())
    return result, complaint, changed


def _name(method: str) -> str:
    """The method under the name the user chose it by."""
    return METHOD_LABELS.get(method, method).split("—")[0].strip()


# ---------------------------------------------------------------- the models

_SESSIONS: dict[str, tuple[str, object]] = {}


def _session(method: str):
    """One session per model per process. Loading the graph is the slow part."""
    path = model_path(method)
    key = f"{path}:{path.stat().st_mtime_ns}"
    cached = _SESSIONS.get(method)
    if cached is None or cached[0] != key:
        import onnxruntime

        options = onnxruntime.SessionOptions()
        # Fatal only. Anything a graph complains about is caught in `fill` and
        # handed to the user as a sentence on the block it happened to; letting
        # onnxruntime also print its own multi-line version to the console just
        # means the same failure is reported twice, once unreadably.
        options.log_severity_level = 4
        _SESSIONS[method] = (
            key,
            onnxruntime.InferenceSession(
                str(path), options, providers=["CPUExecutionProvider"]
            ),
        )
    return _SESSIONS[method][1]


def forget() -> None:
    """Drop every loaded graph and library. For tests, and for swapping files."""
    _SESSIONS.clear()
    _PREFERRED.clear()
    cookie = _LIBRARY.pop("dll_dir", None)
    if cookie is not None:
        # Closed rather than dropped: the search path entry outlives the
        # reference otherwise, and a test that points the library somewhere
        # else would still find the old folder.
        cookie.close()
    _LIBRARY.clear()


def _pad_to(value: int, multiple: int = 8) -> int:
    return ((value + multiple - 1) // multiple) * multiple


def _wanted_size(session) -> tuple[int, int] | None:
    """``(height, width)`` the graph insists on, or None if it takes any size.

    Both shapes are in the wild, sometimes for the same weights. The
    recommended Carve export is fixed at 512x512; the manga fine-tune and AOT
    are dynamic and take whatever they are given as long as both sides are a
    multiple of eight. Asking the graph is the only way to know which is on
    disk, and getting it wrong is a shape error at the first stroke.
    """
    shape = list(session.get_inputs()[0].shape)
    if len(shape) != 4:
        return None
    height, width = shape[2], shape[3]
    if isinstance(height, int) and isinstance(width, int) and height > 0 and width > 0:
        return height, width
    return None


def _to_pixels(out: np.ndarray, scale: str) -> np.ndarray:
    if scale == SCALE_SIGNED:
        out = (out + 1.0) * 127.5
    elif float(out.max()) <= 1.5:
        # Two exports of the same network disagree about this: Carve's returns
        # 0..255 and the manga fine-tune returns 0..1. Guessing turns the repair
        # into a white rectangle, so it is read off the result.
        out = out * 255.0
    return np.clip(out, 0, 255).astype(np.uint8)


def _model_fill(method: str, rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Run one graph over one crop and return the whole crop repainted.

    They all take NCHW float32 - the picture and a single-channel mask where 1
    means "missing" - and they all hand back the crop at the size they were
    given it. What differs is the number range at both ends, which is what the
    `Model` record is for.
    """
    spec = MODELS[method]
    session = _session(method)
    height, width = rgb.shape[:2]

    fixed = _wanted_size(session)
    if fixed is not None:
        inner_h, inner_w = fixed
        picture = cv2.resize(rgb, (inner_w, inner_h), interpolation=cv2.INTER_AREA)
        # Nearest, then re-thresholded: a smoothly resampled mask asks the model
        # to half-repair a ring of pixels around every glyph, which comes back
        # as a halo.
        hole = cv2.resize(mask, (inner_w, inner_h), interpolation=cv2.INTER_NEAREST)
    else:
        picture, hole = rgb, mask
        longest = max(height, width)
        if longest > spec.limit:
            ratio = spec.limit / longest
            size = (max(8, round(width * ratio)), max(8, round(height * ratio)))
            picture = cv2.resize(picture, size, interpolation=cv2.INTER_AREA)
            hole = cv2.resize(hole, size, interpolation=cv2.INTER_NEAREST)
        inner_h, inner_w = picture.shape[:2]
        wide = max(spec.minimum, _pad_to(inner_w))
        tall = max(spec.minimum, _pad_to(inner_h))
        down, right = tall - inner_h, wide - inner_w
        if down or right:
            picture = cv2.copyMakeBorder(
                picture, 0, down, 0, right, cv2.BORDER_REFLECT_101
            )
            hole = cv2.copyMakeBorder(
                hole, 0, down, 0, right, cv2.BORDER_CONSTANT, value=0
            )

    image_in = picture.astype(np.float32).transpose(2, 0, 1)[None]
    image_in = image_in / 255.0 if spec.scale == SCALE_UNIT else image_in / 127.5 - 1.0
    mask_in = (hole > 0).astype(np.float32)[None][None]
    if spec.zero_hole:
        image_in = image_in * (1.0 - mask_in)

    names = [i.name for i in session.get_inputs()]
    raw = np.asarray(session.run(None, {names[0]: image_in, names[1]: mask_in})[0])

    out = raw[0] if raw.ndim == 4 else raw
    if out.shape[0] in (1, 3) and out.shape[0] != out.shape[-1]:
        out = out.transpose(1, 2, 0)
    if out.shape[2] == 1:
        out = np.repeat(out, 3, axis=2)
    out = _to_pixels(out, spec.scale)

    out = out[:inner_h, :inner_w]
    if out.shape[:2] != (height, width):
        out = cv2.resize(out, (width, height), interpolation=cv2.INTER_CUBIC)
    return out


# ----------------------------------------------------------------- PatchMatch


class _Shape(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("channels", ctypes.c_int),
    ]


class _Mat(ctypes.Structure):
    _fields_ = [
        ("data_ptr", ctypes.c_void_p),
        ("shape", _Shape),
        ("dtype", ctypes.c_int),
    ]


#: The library's own depth codes, which are OpenCV's.
_DTYPES = {"uint8": 0, "int8": 1, "uint16": 2, "int16": 3, "int32": 4,
           "float32": 5, "float64": 6}

_LIBRARY: dict[str, object] = {}


def _patchmatch():
    """Load ``patchmatch_inpaint`` once and keep the handle alive.

    The binding is written out here rather than vendored: the reference
    wrapper hard-codes a relative library path, imports PIL, and carries three
    entry points this tool has no use for. What matters is the ABI, and that is
    four fields and one call.
    """
    if "lib" in _LIBRARY:
        return _LIBRARY["lib"]
    path = library_path()
    if path is None:
        raise FileNotFoundError(f"no PatchMatch library in {library_dir()}")
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        # The Windows build is linked against the opencv_world455.dll shipped
        # beside it, which the loader will not find on its own.
        _LIBRARY["dll_dir"] = os.add_dll_directory(str(path.parent))
    lib = ctypes.CDLL(str(path))
    lib.PM_free_pymat.argtypes = [_Mat]
    lib.PM_inpaint.argtypes = [_Mat, _Mat, ctypes.c_int]
    lib.PM_inpaint.restype = _Mat
    lib.PM_set_random_seed.argtypes = [ctypes.c_uint]
    lib.PM_set_verbose.argtypes = [ctypes.c_int]
    lib.PM_set_verbose(0)
    # Fixed, so that re-rendering a block twice gives the same picture twice.
    # The algorithm starts from a random correspondence field, and a preview
    # that shimmers on every keystroke reads as a bug.
    lib.PM_set_random_seed(1)
    _LIBRARY["lib"] = lib
    return lib


def _as_mat(array: np.ndarray) -> _Mat:
    return _Mat(
        ctypes.cast(array.ctypes.data, ctypes.c_void_p),
        _Shape(array.shape[1], array.shape[0], array.shape[2]),
        _DTYPES[str(array.dtype)],
    )


def _patchmatch_fill(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    lib = _patchmatch()
    picture = np.ascontiguousarray(rgb, dtype=np.uint8)
    hole = np.ascontiguousarray((mask > 0).astype(np.uint8)[:, :, None])
    returned = lib.PM_inpaint(
        _as_mat(picture), _as_mat(hole), ctypes.c_int(PATCH_SIZE)
    )
    try:
        borrowed = np.ctypeslib.as_array(
            ctypes.cast(returned.data_ptr, ctypes.POINTER(ctypes.c_uint8)),
            (returned.shape.height, returned.shape.width, returned.shape.channels),
        )
        # Copied before the library frees it - `as_array` is a view into memory
        # that is about to stop being ours.
        out = np.array(borrowed, dtype=np.uint8)
    finally:
        lib.PM_free_pymat(returned)
    return out
