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


def apply_modern_forge_patches(text: str, hotkey: str, ui_scale: str) -> str:
    """Inject Dazed hotkey / UI-scale bootstrap before the Forge bundle runs."""
    text = _strip_existing_bootstrap(text)
    bootstrap = _bootstrap_js(hotkey, ui_scale)
    match = re.search(r"\*/\s*\n", text)
    if not match:
        return bootstrap + "\n" + text
    pos = match.end()
    return text[:pos] + bootstrap + "\n" + text[pos:]
