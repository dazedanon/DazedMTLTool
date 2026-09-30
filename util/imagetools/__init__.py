"""Image text translation toolkit.

Semi-manual by design: an OCR engine reads every image, the user confirms the
boxes and the text in a review editor, DazedTL translates the confirmed export
through its normal pipeline, and only then is anything drawn back into the
image. See ``docs/semi-manual-image-workflow.md`` for why.

Nothing here imports PyQt - the GUI layer sits on top in
``gui/image_text_editor.py``, so the model and the OCR backends stay testable
headless.

**The names below are re-exported lazily**, and that is load-bearing rather
than tidiness. Most of this package needs numpy and OpenCV, which are not in
``requirements.txt`` because only this workflow wants them.
``util.imagetools.resources`` is what downloads them, and it lives in this
package - so importing it must not drag in the very things it exists to fetch.
Binding these eagerly made ``python -m util.imagetools.resources`` fail with
``No module named 'numpy'`` on precisely the checkout it was written for.
"""

from importlib import import_module

_LAZY = {
    "Box": "util.imagetools.geometry",
    "Job": "util.imagetools.job",
    "JobError": "util.imagetools.job",
    "ImageEntry": "util.imagetools.job",
    "TextBlock": "util.imagetools.job",
    "apply_flags": "util.imagetools.job",
    "PENDING": "util.imagetools.job",
    "NEEDS_REVIEW": "util.imagetools.job",
    "CONFIRMED": "util.imagetools.job",
    "TRANSLATED": "util.imagetools.job",
    "RENDERED": "util.imagetools.job",
    "ERROR": "util.imagetools.job",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module), name)
    globals()[name] = value  # bind it, so this costs nothing the second time
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY))
