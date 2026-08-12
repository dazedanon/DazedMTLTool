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
_SHOW_LAUNCHER_DEFAULT_RE = re.compile(
    r"(favorites:\{\},showLauncher:)![01](,quickSaveSlot:1)"
)
_CONFIG_FILENAME_RE = re.compile(r"`forge-config\.json`")


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
  // Forge persists settings through NW.js. Keep that runtime-only file with
  // DazedTL's other ignored per-game metadata, and preserve settings written
  // by older installs at the game root.
  try {{
    var forgeFs = window.require && window.require("fs");
    if (forgeFs) {{
      var forgeDir = ".dazedtl";
      var forgeConfig = forgeDir + "/forge-config.json";
      var legacyForgeConfig = "forge-config.json";
      if (!forgeFs.existsSync(forgeDir)) forgeFs.mkdirSync(forgeDir);
      if (forgeFs.existsSync(legacyForgeConfig) && !forgeFs.existsSync(forgeConfig)) {{
        forgeFs.renameSync(legacyForgeConfig, forgeConfig);
      }}
    }}
  }} catch (e) {{}}
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
  // The keyboard shortcut is always available, so keep the floating launcher
  // hidden even when an older Forge install saved it as enabled.
  try {{
    var config = JSON.parse(localStorage.getItem("forge:config") || "{{}}");
    config.showLauncher = false;
    localStorage.setItem("forge:config", JSON.stringify(config));
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


def _disable_launcher_default(text: str) -> str:
    """Hide modern Forge's floating launcher; the toggle shortcut remains active."""
    text, n = _SHOW_LAUNCHER_DEFAULT_RE.subn(r"\g<1>!1\2", text, count=1)
    if n == 0:
        raise ValueError("Could not disable modern Forge launcher default")
    return text


def _relocate_config_file(text: str) -> str:
    """Store Forge's runtime settings under the ignored game metadata folder."""
    text, count = _CONFIG_FILENAME_RE.subn(
        "`.dazedtl/forge-config.json`", text, count=1
    )
    if count != 1:
        raise ValueError("Could not relocate modern Forge config file")
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
    ]
    for old, new in replacements:
        if old not in text:
            raise ValueError(f"Could not patch Forge keyCode read: missing {old!r}")
        text = text.replace(old, new, 1)

    # The minifier changes the key-set and class identifiers between upstream
    # builds, so patch the stable method shape instead of pinning those names.
    from_event = re.compile(
        r"static fromEvent\((?P<event>[A-Za-z_$][\w$]*)\)\{return "
        r"(?P<body>[^{}]+)\}(?=static _fromCombiningAloneEvent)"
    )

    def patch_from_event(match: re.Match) -> str:
        event = match.group("event")
        body, count = re.subn(
            rf"\b{re.escape(event)}\.keyCode\b",
            f"window.__dazedKeyCode({event})",
            match.group("body"),
        )
        if count != 2:
            raise ValueError(
                "Could not patch Forge fromEvent keyCode reads: "
                f"expected 2, found {count}"
            )
        return f"static fromEvent({event}){{return {body}}}"

    text, count = from_event.subn(patch_from_event, text, count=1)
    if count != 1:
        raise ValueError("Could not patch Forge fromEvent shortcut parser")
    return text


def apply_modern_forge_patches(text: str, hotkey: str, ui_scale: str) -> str:
    """Inject Dazed hotkey / UI-scale bootstrap and harden shortcut handling."""
    text = _strip_existing_bootstrap(text)
    text = _patch_toggle_ui_default(text, hotkey)
    text = _disable_launcher_default(text)
    text = _relocate_config_file(text)
    text = _patch_keycode_reads(text)
    bootstrap = _bootstrap_js(hotkey, ui_scale)
    match = re.search(r"\*/\s*\n", text)
    if not match:
        return bootstrap + "\n" + text
    pos = match.end()
    return text[:pos] + bootstrap + "\n" + text[pos:]
