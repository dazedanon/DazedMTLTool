"""UI scale patches applied at Forge install/apply time only.

Vanilla Forge_MZ.js / Forge_MV.js from len's repo are never modified on disk.
prepare_forge_js() reads the bundled upstream copy and applies these patches
in memory before writing the result into the game folder.
"""

from __future__ import annotations

import re

_UI_SCALE_HELP_MZ = (
    " *\n"
    " * @param uiScale\n"
    " * @text UI Scale\n"
    " * @desc Overlay size. Use auto to match game width, or a number like 1.5 or 2.\n"
    " * @type string\n"
    " * @default auto\n"
)

_UI_SCALE_HELP_MV = (
    " *\n"
    " * @param UiScale\n"
    " * @desc Overlay size. Use auto to match the window, or a number like 1.5 or 2.\n"
    " * @default auto\n"
)

_SCALE_BLOCK = """\
    function resolveUiScale(v) {
      if (v !== 'auto' && v != null && String(v).trim() !== '') {
        var n = parseFloat(v);
        if (!isNaN(n) && n > 0) return Math.max(0.75, Math.min(3, n));
      }
      var base = 816;
      var gameW = (typeof Graphics !== 'undefined' && Graphics.width) ? Graphics.width : 0;
      var viewW = window.innerWidth || document.documentElement.clientWidth || base;
      var w = Math.max(gameW || base, viewW);
      var scale = w / base;
      var dpr = window.devicePixelRatio || 1;
      if (dpr > 1.15) scale *= Math.min(2, 0.75 + dpr * 0.35);
      return Math.max(1, Math.min(2.75, scale));
    }
    function scalePx(n, fx) {
      if (!fx || fx === 1) return n;
      return Math.round(n * fx);
    }
    function scalePxCss(css, fx) {
      if (!fx || fx === 1) return css;
      return css.replace(/(\\d+(?:\\.\\d+)?)px/g, function (_, n) {
        return scalePx(parseFloat(n), fx) + 'px';
      });
    }
    function scaleStyle(style, fx) {
      if (!style || !fx || fx === 1) return style;
      return style.replace(/(\\d+(?:\\.\\d+)?)px/g, function (_, n) {
        return scalePx(parseFloat(n), fx) + 'px';
      });
    }
    var uiFx = resolveUiScale(API._uiScale || 'auto');
"""

_SCROLLBAR_OLD = (
    "::-webkit-scrollbar{width:9px;height:9px}\\\n"
    "::-webkit-scrollbar-track{background:transparent}\\\n"
    "::-webkit-scrollbar-thumb{background:var(--fg-border-strong);border-radius:5px}\\\n"
    "::-webkit-scrollbar-thumb:hover{background:var(--fg-text-faint)}\";"
)

_SCROLLBAR_NEW = (
    ".fg-list::-webkit-scrollbar,.fg-rail::-webkit-scrollbar,.fg-detail::-webkit-scrollbar{width:9px}\\\n"
    ".fg-list::-webkit-scrollbar-thumb,.fg-detail::-webkit-scrollbar-thumb{background:var(--fg-border-strong);border-radius:5px}\";"
)


def _sub(text: str, pattern: str, repl, *, label: str, count: int = 1) -> str:
    new_text, n = re.subn(pattern, repl, text, count=count)
    if n != count:
        raise ValueError(f"Forge UI scale patch failed ({label}): expected {count} replacement(s), got {n}")
    return new_text


def apply_ui_scale_patches(text: str, engine: str) -> str:
    """Return upstream Forge JS with Dazed overlay scaling (install-time only)."""
    if engine == "MZ":
        text = _sub(
            text,
            r"( \* @default 0\n)( \*\n \* @command open)",
            rf"\1{_UI_SCALE_HELP_MZ}\2",
            label="MZ uiScale param",
        )
        scaffold_scale = "    window.Forge._uiScale = (P.uiScale || 'auto').trim();\n"
        scaffold_pattern = (
            r"(    window\.Forge\._itemMaxOverride = Number\(P\.itemMaxOverride\) \|\| 0;\n)"
        )
    else:
        text = _sub(
            text,
            r"( \* @default 0\n)( \*\n \* @help)",
            rf"\1{_UI_SCALE_HELP_MV}\2",
            label="MV UiScale param",
        )
        scaffold_scale = "    window.Forge._uiScale = (P.UiScale || 'auto').trim();\n"
        scaffold_pattern = (
            r"(    window\.Forge\._itemMaxOverride = Number\(P\.ItemMaxOverride\) \|\| 0;\n)"
        )

    text = _sub(
        text,
        r"(_speedBoost: 2) \};",
        r"\1, _uiScale: 'auto' };",
        label="MTC _uiScale default",
    )

    text = _sub(
        text,
        r"(    function load\(k, d\) \{ try \{ var s = localStorage\.getItem\(LS \+ k\); return s == null \? d : JSON\.parse\(s\); \} catch \(e\) \{ return d; \} \}\n)"
        r"(    // persisted speed settings)",
        lambda m: m.group(1) + _SCALE_BLOCK + m.group(2),
        label="UI scale helpers",
    )

    text = _sub(
        text,
        r"else if \(k === 'style'\) n\.setAttribute\('style', props\[k\]\);",
        "else if (k === 'style') n.setAttribute('style', scaleStyle(props[k], uiFx));",
        label="el() style scaling",
    )

    text = text.replace(_SCROLLBAR_OLD, _SCROLLBAR_NEW)

    text = _sub(
        text,
        "pointer-events:none!important';",
        "pointer-events:none!important;overflow:visible!important';",
        label="host overflow",
    )

    text = _sub(
        text,
        r"shadow\.appendChild\(el\('style', \{ text: CSS \}\)\);",
        "shadow.appendChild(el('style', { text: scalePxCss(CSS, uiFx) }));",
        label="scaled stylesheet",
    )

    replacements = [
        (
            r"var st = load\('panel', \{ x: 16, y: 16, w: Math\.min\(880, vw - 32\), h: Math\.min\(560, vh - 32\) \}\);",
            "var st = load('panel', { x: scalePx(16, uiFx), y: scalePx(16, uiFx), w: Math.min(scalePx(880, uiFx), vw - scalePx(32, uiFx)), h: Math.min(scalePx(560, uiFx), vh - scalePx(32, uiFx)) });",
            "panel defaults",
        ),
        (
            r"st\.w = Math\.max\(420, Math\.min\(st\.w, vw - 8\)\); st\.h = Math\.max\(320, Math\.min\(st\.h, vh - 8\)\);",
            "st.w = Math.max(scalePx(420, uiFx), Math.min(st.w, vw - scalePx(8, uiFx))); st.h = Math.max(scalePx(320, uiFx), Math.min(st.h, vh - scalePx(8, uiFx)));",
            "panel bounds",
        ),
        (
            r"var lp = load\('launcherPos', \{ x: vw - 56, y: vh - 56 \}\);",
            "var lp = load('launcherPos', { x: vw - scalePx(56, uiFx), y: vh - scalePx(56, uiFx) });",
            "launcher defaults",
        ),
        (
            r"lp\.x = Math\.max\(4, Math\.min\(lp\.x, vw - 46\)\); lp\.y = Math\.max\(4, Math\.min\(lp\.y, vh - 46\)\);",
            "lp.x = Math.max(scalePx(4, uiFx), Math.min(lp.x, vw - scalePx(46, uiFx))); lp.y = Math.max(scalePx(4, uiFx), Math.min(lp.y, vh - scalePx(46, uiFx)));",
            "launcher bounds",
        ),
        (
            r"Math\.min\(window\.innerHeight - 30, oy \+ dy\)",
            "Math.min(window.innerHeight - scalePx(30, uiFx), oy + dy)",
            "drag height clamp",
        ),
        (
            r"var w = Math\.max\(480, ow \+ ev\.clientX - sx\), h = Math\.max\(360, oh \+ ev\.clientY - sy\);",
            "var w = Math.max(scalePx(480, uiFx), ow + ev.clientX - sx), h = Math.max(scalePx(360, uiFx), oh + ev.clientY - sy);",
            "resize minimums",
        ),
        (
            r"var rowH = opts\.rowH \|\| 30, pool = \[\], model = \[\], view = \[\], query = '';",
            "var rowH = opts.rowH || scalePx(30, uiFx), pool = [], model = [], view = [], query = '';",
            "virtual list row height",
        ),
    ]
    for pattern, repl, label in replacements:
        text = _sub(text, pattern, repl, label=label)

    text = _sub(text, scaffold_pattern, lambda m: m.group(1) + scaffold_scale, label="scaffolding uiScale")
    return text
