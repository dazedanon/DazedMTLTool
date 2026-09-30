"""Claim the Visual C++ runtime before Qt does. Windows only, best effort.

PyQt5 ships its own copy of the Visual C++ runtime in ``PyQt5/Qt5/bin`` and
puts that folder on the DLL search path when it is imported. On this machine
that copy is 14.26 where Windows itself has 14.51, and onnxruntime is built
against something newer than 14.26: importing it after Qt has loaded fails with
"DLL load failed ... a dynamic link library (DLL) initialization routine
failed", which is not a missing-package error and does not name the runtime.

Windows resolves a DLL request against the modules already loaded in the
process before it searches anywhere, and only one module of a given name can be
loaded at a time. So whoever loads ``msvcp140.dll`` first decides which one
everybody gets, and the newer runtime is backward compatible - Qt is perfectly
happy with it, while onnxruntime is not happy with Qt's.

The catch is that this only works *before* Qt's libraries load. Afterwards the
old copy is already resident under that name and nothing can displace it, which
is why this is called from the entry point rather than from the module that
wants onnxruntime.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

#: Lowest-level first: `msvcp140` depends on `vcruntime140`, and loading it
#: first would resolve *that* dependency through the ordinary search - which is
#: the search this exists to pre-empt.
RUNTIME = (
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "concrt140.dll",
)

_done = False


def prepare() -> list[str]:
    """Load the system runtime by absolute path. Returns what was claimed.

    Safe to call more than once and safe to call on any platform; anything that
    does not load is skipped, because a machine missing one of these is a
    machine where the ordinary search was going to be used anyway.
    """
    global _done
    if _done or sys.platform != "win32":
        return []
    _done = True

    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    claimed = []
    for name in RUNTIME:
        path = system / name
        if not path.is_file():
            continue
        try:
            ctypes.CDLL(str(path))
        except OSError:
            continue
        claimed.append(name)
    return claimed
