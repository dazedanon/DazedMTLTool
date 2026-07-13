"""Install-time patches for the rewritten Forge plugin (unified forge.js)."""

from __future__ import annotations

import json
import re

_BOOTSTRAP_START = "/*<DazedMTLTool-Forge-bootstrap>*/"
_BOOTSTRAP_END = "/*</DazedMTLTool-Forge-bootstrap>*/"

_MODIFIER_ALIASES = {
    "control": "ctrl",
    "ctrl": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "meta": "meta",
    "cmd": "meta",
    "command": "meta",
    "win": "meta",
}

_TOGGLE_UI_KEYSTR_RE = re.compile(
    r"(id:`toggle_ui`,name:`Toggle Cheat UI`,desc:`Show/Hide the cheat panel`,keyStr:`)[^`]+(`)"
)


def forge_key_str(hotkey: str) -> str:
    """Convert a Dazed forgeHotkey value to Forge shortcut keyStr format."""
    raw = (hotkey or "F10").strip()
    if not raw:
        return "f10"
    parts = re.split(r"\s*\+\s*|\s+", raw)
    out: list[str] = []
    for part in parts:
        token = part.strip().lower()
        if not token:
            continue
        mapped = _MODIFIER_ALIASES.get(token)
        if mapped:
            if mapped not in out:
                out.append(mapped)
        else:
            out.append(token)
    return " ".join(out) or "f10"


def _bootstrap_js(hotkey: str, ui_scale: str) -> str:
    key_str = json.dumps(forge_key_str(hotkey))
    scale = json.dumps(str(ui_scale or "auto").strip() or "auto")
    return f"""{_BOOTSTRAP_START}
(function () {{
  var toggleKey = {key_str};
  var uiScale = {scale};
  // Forge's shortcut matcher uses legacy keyCode. Some NW.js/Wine builds deliver
  // keydown with keyCode=0 while still setting key/code - map those back.
  window.__dazedKeyCode = function (e) {{
    var kc = e.keyCode || e.which || 0;
    if (kc) return kc;
    var key = String(e.key || "").toLowerCase();
    var code = String(e.code || "");
    if (key === "control") return 17;
    if (key === "alt") return 18;
    if (key === "shift") return 16;
    if (key === "meta") return 91;
    var fm = /^f(\\d{{1,2}})$/.exec(key) || /^f(\\d{{1,2}})$/i.exec(code);
    if (fm) return 111 + parseInt(fm[1], 10);
    var km = /^key([a-z])$/i.exec(code);
    if (km) return km[1].toUpperCase().charCodeAt(0);
    if (key.length === 1) {{
      var c = key.charCodeAt(0);
      if (c >= 97 && c <= 122) return c - 32;
      if (c >= 48 && c <= 57) return c;
    }}
    var dm = /^digit([0-9])$/i.exec(code);
    if (dm) return 48 + parseInt(dm[1], 10);
    return 0;
  }};
  try {{
    var saved = JSON.parse(localStorage.getItem("forge:shortcuts") || "{{}}");
    saved.toggle_ui = Object.assign({{}}, saved.toggle_ui, {{ keyStr: toggleKey, enabled: true }});
    localStorage.setItem("forge:shortcuts", JSON.stringify(saved));
  }} catch (e) {{}}
  function resolveUiScale(v) {{
    if (v !== "auto" && v != null && String(v).trim() !== "") {{
      var n = parseFloat(v);
      if (!isNaN(n) && n > 0) return Math.max(0.75, Math.min(3, n));
    }}
    var base = 816;
    var gameW = (typeof Graphics !== "undefined" && Graphics.width) ? Graphics.width : 0;
    var viewW = window.innerWidth || document.documentElement.clientWidth || base;
    var w = Math.max(gameW || base, viewW);
    var scale = w / base;
    var dpr = window.devicePixelRatio || 1;
    if (dpr > 1.15) scale *= Math.min(2, 0.75 + dpr * 0.35);
    return Math.max(1, Math.min(2.75, scale));
  }}
  function applyUiScale() {{
    var host = document.getElementById("forge-mvmz-host");
    if (!host) return;
    var fx = resolveUiScale(uiScale);
    host.style.zoom = String(fx);
  }}
  if (!window.__dazedForgeUiScaleHook) {{
    window.__dazedForgeUiScaleHook = true;
    var observer = new MutationObserver(applyUiScale);
    observer.observe(document.documentElement, {{ childList: true, subtree: true }});
    window.addEventListener("resize", applyUiScale);
    setInterval(applyUiScale, 500);
  }}
  applyUiScale();
}})();
{_BOOTSTRAP_END}"""


def _strip_existing_bootstrap(text: str) -> str:
    while True:
        start = text.find(_BOOTSTRAP_START)
        if start < 0:
            return text
        end = text.find(_BOOTSTRAP_END, start)
        if end < 0:
            return text
        text = text[:start] + text[end + len(_BOOTSTRAP_END) :]
    return text


def _patch_toggle_ui_default(text: str, hotkey: str) -> str:
    """Rewrite Forge's built-in toggle_ui default (Ctrl C) to the Dazed hotkey."""
    key = forge_key_str(hotkey)
    text, n = _TOGGLE_UI_KEYSTR_RE.subn(rf"\g<1>{key}\2", text, count=1)
    if n == 0:
        raise ValueError("Could not patch toggle_ui keyStr in modern Forge bundle")
    return text


def _patch_keycode_reads(text: str) -> str:
    """Route Forge shortcut key reads through the keyCode polyfill."""
    replacements = [
        (
            "$.currentKey.add(e.keyCode)",
            "$.currentKey.add(window.__dazedKeyCode(e))",
        ),
        (
            "$.currentKey.remove(e.keyCode)",
            "$.currentKey.remove(window.__dazedKeyCode(e))",
        ),
        (
            "static fromEvent(t){return Jc.has(t.keyCode)?e._fromCombiningAloneEvent(t):"
            "new e(t.keyCode,t.ctrlKey,t.altKey,t.shiftKey,t.metaKey)}",
            "static fromEvent(t){var k=window.__dazedKeyCode(t);return Jc.has(k)?"
            "e._fromCombiningAloneEvent(t):new e(k,t.ctrlKey,t.altKey,t.shiftKey,t.metaKey)}",
        ),
    ]
    for old, new in replacements:
        if old not in text:
            raise ValueError(f"Could not patch Forge keyCode read: missing {old!r}")
        text = text.replace(old, new, 1)
    return text


def apply_modern_forge_patches(text: str, hotkey: str, ui_scale: str) -> str:
    """Inject Dazed hotkey / UI-scale bootstrap and harden shortcut handling."""
    text = _strip_existing_bootstrap(text)
    text = _patch_toggle_ui_default(text, hotkey)
    text = _patch_keycode_reads(text)
    bootstrap = _bootstrap_js(hotkey, ui_scale)
    match = re.search(r"\*/\s*\n", text)
    if not match:
        return bootstrap + "\n" + text
    pos = match.end()
    return text[:pos] + bootstrap + "\n" + text[pos:]
