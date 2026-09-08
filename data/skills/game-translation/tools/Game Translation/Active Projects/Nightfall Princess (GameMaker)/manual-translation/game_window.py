"""Local interaction with the task's game window for screenshot-based QA."""
import argparse
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import time
from PIL import ImageGrab

u = c.WinDLL("user32", use_last_error=True)
u.FindWindowW.argtypes = [w.LPCWSTR, w.LPCWSTR]
u.FindWindowW.restype = w.HWND
u.GetForegroundWindow.restype = w.HWND
u.ShowWindow.argtypes = [w.HWND, c.c_int]
u.SetForegroundWindow.argtypes = [w.HWND]
u.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
u.ClientToScreen.argtypes = [w.HWND, c.POINTER(w.POINT)]
u.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
u.SetProcessDPIAware()

p = argparse.ArgumentParser()
p.add_argument("--title", default="Nightfall Princess | Translated by len")
p.add_argument("--capture", type=Path)
p.add_argument("--click", nargs=2, type=int, metavar=("GAME_X", "GAME_Y"))
p.add_argument("--move", nargs=2, type=int, metavar=("GAME_X", "GAME_Y"))
p.add_argument("--key", type=int, help="Windows virtual key code")
p.add_argument("--hold", type=float, default=0.12, help="Key hold duration, up to 5 seconds")
p.add_argument("--close", action="store_true")
a = p.parse_args()
assert 0 < a.hold <= 5
assert a.title.startswith("Nightfall Princess")
h = u.FindWindowW(None, a.title)
assert h, "Game window not found"
if a.close:
    u.PostMessageW(h, 0x10, 0, 0)
else:
    u.ShowWindow(h, 9)
    u.SetForegroundWindow(h)
    time.sleep(0.5)
    assert u.GetForegroundWindow() == h, "Game did not take focus"
    rect = w.RECT()
    u.GetClientRect(h, c.byref(rect))
    origin = w.POINT(0, 0)
    u.ClientToScreen(h, c.byref(origin))
    point = a.click or a.move
    if point:
        px = origin.x + round(point[0] * rect.right / 1920)
        py = origin.y + round(point[1] * rect.bottom / 1080)
        u.SetCursorPos(px, py)
        if a.click:
            u.mouse_event(0x0002, 0, 0, 0, 0)
            time.sleep(0.08)
            u.mouse_event(0x0004, 0, 0, 0, 0)
    if a.key is not None:
        assert u.GetForegroundWindow() == h
        u.keybd_event(a.key, 0, 0, 0)
        try:
            time.sleep(a.hold)
        finally:
            u.keybd_event(a.key, 0, 2, 0)
    time.sleep(0.8)
    if a.capture:
        a.capture.parent.mkdir(parents=True, exist_ok=True)
        assert u.GetForegroundWindow() == h
        # An input can resize/move the window; capture its current client area.
        u.GetClientRect(h, c.byref(rect))
        origin = w.POINT(0, 0)
        u.ClientToScreen(h, c.byref(origin))
        ImageGrab.grab(bbox=(origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom)).save(a.capture)
        print(str(a.capture.resolve()))
