"""Small synchronous event callbacks shared by headless workers."""
import threading


class TaskSignal:
    """Synchronous callbacks; desktop adapters forward them over a private pipe."""

    def __init__(self):
        self._callbacks = []
        self._lock = threading.RLock()

    def connect(self, callback):
        with self._lock:
            self._callbacks.append(callback)

    def emit(self, *args):
        with self._lock:
            callbacks = tuple(self._callbacks)
        for callback in callbacks:
            callback(*args)
