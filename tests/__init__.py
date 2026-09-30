"""Test package.

The one thing done here is claiming the system Visual C++ runtime before
anything imports PyQt5, exactly as the launchers do. Without it, running the
render tests alone and running them alongside the editor tests disagree about
which copy of the runtime the process holds, and onnxruntime loads in one case
and not the other. A no-op off Windows. See util/msvc_runtime.py.
"""

from util.msvc_runtime import prepare

prepare()
