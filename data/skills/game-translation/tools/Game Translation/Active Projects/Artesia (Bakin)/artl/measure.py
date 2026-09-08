#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
measure.py - rendered text width, in pixels, using the font the game uses.

Bakin r64268 has **no Font rom resource**. There is no per-widget font, no
`Font.Size * Font.DefaultScale`, and no `UseToMessageDefault` to read. There is
exactly one setting - `GameSettings.gameFont` - and on this game it holds

    游明朝 Demibold

which is an **installed system font**, not one shipped in the pack. Two
consequences that have to be stated rather than hidden:

  * The player's screen depends on what they have installed. Yu Mincho ships
    with Windows as an optional Japanese supplemental font, so a player without
    it sees the engine's substitute and every width here is approximate for
    them too.
  * This machine may not have it either. `resolve()` reports which file it
    actually opened, and `substituted` says whether that was the real thing.
    `fit.py` prints it. Never let a measurement quietly claim to be the game's.

The pack does ship `font.ttf` (M+SmileBoom bold), which is Bakin's bundled
default - it is what the engine uses when `gameFont` resolves to nothing. It is
the right fallback here for exactly that reason.

Width is `MeasureString(font, s).X * MenuItem.scale.X`. `textScale` is 1.0 on
every text-bearing widget in this game and is applied anyway.
"""

import os
import sys

_FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")

# Family name -> the files Windows actually ships it in. Resolving through the
# registry as well, below, because a user-installed font is not in this table.
_KNOWN = {
    "游明朝 demibold": ["yumindb.ttf", "YuMinDB.ttf"],
    "游明朝": ["yumin.ttf", "YuMin.ttf"],
    "yu mincho demibold": ["yumindb.ttf"],
    "yu mincho": ["yumin.ttf"],
    "yumincho": ["yumin.ttf"],
    "ms mincho": ["msmincho.ttc"],
    "ＭＳ 明朝": ["msmincho.ttc"],
    "游ゴシック": ["YuGothR.ttc"],
    "yu gothic": ["YuGothR.ttc"],
    "yu gothic light": ["YuGothL.ttc"],
    "yu gothic medium": ["YuGothM.ttc"],
    "meiryo": ["meiryo.ttc"],
    "メイリオ": ["meiryo.ttc"],
    "noto serif jp": ["NotoSerifJP-Regular.otf"],
}


def _registry_fonts():
    """{lowercased family name: absolute path} from the Windows font registry."""
    out = {}
    if sys.platform != "win32":
        return out
    try:
        import winreg
    except ImportError:
        return out
    for root, key in ((winreg.HKEY_LOCAL_MACHINE,
                       r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
                      (winreg.HKEY_CURRENT_USER,
                       r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")):
        try:
            h = winreg.OpenKey(root, key)
        except OSError:
            continue
        try:
            i = 0
            while True:
                try:
                    name, val, _t = winreg.EnumValue(h, i)
                except OSError:
                    break
                i += 1
                if not isinstance(val, str):
                    continue
                path = val if os.path.isabs(val) else os.path.join(_FONT_DIR, val)
                # "Yu Mincho Demibold & Yu Mincho Demibold Italic (TrueType)"
                base = name.split("(")[0].strip()
                for part in base.split("&"):
                    part = part.strip().lower()
                    if part:
                        out.setdefault(part, path)
        finally:
            h.Close()
    return out


class Metrics(object):
    """Pixel width of a string at the game's font size."""

    def __init__(self, path, size, family, substituted, requested):
        from PIL import ImageFont
        self.path = path
        self.size = size
        self.family = family
        self.substituted = substituted
        self.requested = requested
        self._font = ImageFont.truetype(path, size)
        self._cache = {}

    def width(self, text, scale=1.0):
        """Rendered width in pixels. Newlines are measured per line."""
        if not text:
            return 0.0
        best = 0.0
        for line in text.split("\n"):
            w = self._cache.get(line)
            if w is None:
                w = self._cache[line] = self._font.getlength(line)
            best = max(best, w)
        return best * scale

    def lines(self, text):
        return text.count("\n") + 1 if text else 0

    def describe(self):
        if not self.substituted:
            return "font %s at %dpx (%s)" % (self.family, self.size, self.path)
        return ("font SUBSTITUTED: wanted %r, measuring with %s at %dpx (%s). "
                "Widths are approximate - and so is the player's screen if "
                "they do not have the requested font either."
                % (self.requested, self.family, self.size, self.path))


def resolve(cfg, size=24, bundled=None):
    """Metrics for the game's font, substituting audibly rather than silently.

    `size` is the pixel size to measure at. Bakin r64268 exposes no font-size
    field on the widget, so this is a calibration constant, not a reading -
    `tools/calibrate_font.py` derives it from an OBSERVED render and it lives
    in the config as `font_size`. Not from the shipped Japanese: measured over
    44,056 author-placed breaks, the "the next word would still have fitted"
    rate never bottoms out (99.97% at 16px, 90.52% at 24px), because a Japanese
    author breaks dialogue at phrase boundaries rather than at the margin."""
    # Measure the font the game will ACTUALLY ask for. When `game_font_override`
    # is set we rewrite `GameSettings.gameFont`, so measuring the author's
    # original name would describe a render that no longer happens.
    want = cfg.get("game_font_override") or cfg.get("game_font") or ""
    order = [want] + list(cfg.get("font_fallbacks") or [])
    reg = _registry_fonts()

    for i, fam in enumerate(order):
        if not fam:
            continue
        low = fam.lower()
        cands = []
        if low in reg:
            cands.append(reg[low])
        for fn in _KNOWN.get(low, []):
            cands.append(os.path.join(_FONT_DIR, fn))
        for p in cands:
            if not os.path.exists(p):
                continue
            try:
                return Metrics(p, size, fam, i > 0, want)
            except Exception:
                continue

    bundled = bundled or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "proj", "font.ttf")
    if os.path.exists(bundled):
        return Metrics(bundled, size, "M+SmileBoom (the engine's bundled "
                       "default, shipped in this game's pack)", True, want)
    raise SystemExit(
        "No usable font. Wanted %r, tried %s, and the bundled %s is missing."
        % (want, ", ".join(order[1:]) or "no fallbacks", bundled))


_CURRENT = [None]


def reset(cfg, size=None):
    _CURRENT[0] = resolve(cfg, size or cfg.get("font_size", 24))
    return _CURRENT[0]


def current(cfg=None):
    if _CURRENT[0] is None:
        if cfg is None:
            raise RuntimeError("measure.reset(cfg) has not been called")
        reset(cfg)
    return _CURRENT[0]
