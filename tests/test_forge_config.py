#!/usr/bin/env python3
"""Tests for install-time Forge plugin customization."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from util.forge.config import bundled_plugin_path, prepare_forge_js  # noqa: E402
from util.forge.installer import install  # noqa: E402


class ForgeConfigTests(unittest.TestCase):
    def test_modern_mz_hides_launcher_and_keeps_shortcut(self):
        output = prepare_forge_js(
            "MZ",
            cfg={"forgeHotkey": "F9", "uiScale": "auto"},
        )

        self.assertIn("favorites:{},showLauncher:!1,quickSaveSlot:1", output)
        self.assertIn("keyStr:`f9`", output)
        self.assertIn(
            "window.__dazedForgeConfigPath || `.dazedtl/forge-config.json`",
            output,
        )
        self.assertIn("window.__dazedForgeFs", output)
        self.assertIn('"dazedtl:forge-config:"', output)
        self.assertIn('typeof require === "function"', output)
        self.assertNotIn(
            "let e=window.require;if(typeof e!=`function`)return;"
            "let t=e(`fs`);if(!t)return;",
            output,
        )
        self.assertNotIn("bl=`forge-config.json`", output)

        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            game.joinpath("js", "plugins").mkdir(parents=True)
            game.joinpath("js", "plugins.js").write_text(
                "var $plugins = [\n];\n", encoding="utf-8"
            )

            ok, message = install(game, cfg={"forgeHotkey": "F10"})

            self.assertTrue(ok, message)
            self.assertTrue(game.joinpath(".dazedtl").is_dir())
            ignore = game.joinpath(".gitignore").read_text(encoding="utf-8")
            self.assertIn("/.dazedtl/*", ignore.splitlines())
            self.assertNotIn(
                "!/.dazedtl/forge-config.json", ignore.splitlines()
            )
            installed = game.joinpath("js", "plugins", "Forge_MZ.js").read_text(
                encoding="utf-8"
            )
            self.assertIn(
                "window.__dazedForgeConfigPath || `.dazedtl/forge-config.json`",
                installed,
            )

    def test_packaged_nw_game_persists_config_and_keeps_f8_toggle_active(self):
        """Packaged games persist settings and can close Forge from Keys."""
        output = prepare_forge_js(
            "MZ",
            cfg={"forgeHotkey": "F9", "uiScale": "auto"},
        )
        marker = "/*</DazedMTLTool-Forge-bootstrap>*/"
        bootstrap = output[: output.index(marker) + len(marker)]
        controller_start = output.index("$={currentKey:")
        controller_end = output.index("},zl=I(", controller_start) + 1
        shortcut_controller = output[controller_start:controller_end]

        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            game.joinpath("index.html").write_text("", encoding="utf-8")
            config_path = game / ".dazedtl" / "forge-config.json"
            script = f"""
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const values = new Map([
  ["forge:shortcuts", JSON.stringify({{quick_save: {{keyStr: "ctrl s", enabled: false}}}})],
  ["forge:config", JSON.stringify({{autoOpen: true, showLauncher: true}})],
  ["forge:lastTab", "logs"]
]);
global.window = global;
global.nw = {{App: {{startPath: {json.dumps(str(game))}}}}};
global.location = {{protocol: "chrome-extension:", pathname: "/index.html"}};
global.getSelection = () => null;
global.localStorage = {{
  get length() {{ return values.size; }},
  key(index) {{ return Array.from(values.keys())[index] || null; }},
  getItem(key) {{ return values.has(key) ? values.get(key) : null; }},
  setItem(key, value) {{ values.set(key, String(value)); }},
  removeItem(key) {{ values.delete(key); }}
}};
global.document = {{
  activeElement: null,
  getElementById() {{ return null; }},
  documentElement: {{clientWidth: 816}}
}};
global.MutationObserver = class {{ observe() {{}} }};
global.addEventListener = () => {{}};
global.setInterval = () => 0;
eval({json.dumps(bootstrap)});
assert.strictEqual(window.__dazedForgeConfigPath, {json.dumps(str(config_path))});
const saved = JSON.parse(fs.readFileSync({json.dumps(str(config_path))}, "utf8"));
assert.deepStrictEqual(saved.shortcuts.quick_save, {{keyStr: "ctrl s", enabled: false}});
assert.deepStrictEqual(saved.shortcuts.toggle_ui, {{keyStr: "f9", enabled: true}});
assert.strictEqual(saved.config.autoOpen, true);
assert.strictEqual(saved.config.showLauncher, false);
assert.strictEqual(saved.lastTab, "logs");
assert.strictEqual(path.dirname(window.__dazedForgeConfigPath), path.join({json.dumps(str(game))}, ".dazedtl"));

global.ml = {{Shortcuts: "shortcuts"}};
global.Q = {{visible: true, activeTab: ml.Shortcuts}};
global.Ol = {{getItem() {{ return null; }}, setItem() {{}}}};
global.Dt = (...objects) => Object.assign({{}}, ...objects);
global.Rl = {{
  createEmpty() {{
    return {{
      keys: new Set(),
      add(code) {{ this.keys.add(code); }},
      remove(code) {{ this.keys.delete(code); }},
      adjustCombiningKey() {{}},
      contains(expected) {{ return expected.equals(this); }}
    }};
  }},
  fromString(value) {{
    const code = value.toLowerCase() === "f8" ? 119 : 83;
    return {{
      combiningKeyAlone: false,
      equals(current) {{
        return current.keys.size === 1 && current.keys.has(code);
      }}
    }};
  }}
}};
global.$ = null;
eval({json.dumps(shortcut_controller)});
let otherShortcutRuns = 0;
$.shortcuts = [
  {{id: "toggle_ui", keyStr: "f8", enabled: true, onEnter() {{ Q.visible = !Q.visible; }}}},
  {{id: "quick_save", keyStr: "s", enabled: true, onEnter() {{ otherShortcutRuns++; }}}}
];
const keyEvent = (type, keyCode) => ({{
  type,
  keyCode,
  repeat: false,
  preventDefault() {{}},
  stopPropagation() {{}}
}});
$.onKeyDown(keyEvent("keydown", 119));
assert.strictEqual(Q.visible, false);
$.onKeyUp(keyEvent("keyup", 119));
$.onKeyDown(keyEvent("keydown", 119));
assert.strictEqual(Q.visible, true);
$.onKeyUp(keyEvent("keyup", 119));
$.onKeyDown(keyEvent("keydown", 83));
assert.strictEqual(otherShortcutRuns, 0);
$.onKeyUp(keyEvent("keyup", 83));
"""
            result = subprocess.run(
                ["node", "-e", script],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(config_path.is_file())

    def test_mv_uses_modern_bundle_and_keeps_legacy_fallback_available(self):
        self.assertEqual(bundled_plugin_path("MV"), bundled_plugin_path("MZ"))

        output = prepare_forge_js(
            "MV",
            cfg={"forgeHotkey": "F9", "uiScale": "auto"},
        )

        self.assertIn("favorites:{},showLauncher:!1,quickSaveSlot:1", output)
        self.assertIn("keyStr:`f9`", output)

        legacy = ROOT / "util" / "forge" / "upstream" / "Forge_MV.js"
        self.assertTrue(legacy.is_file())
        self.assertNotEqual(bundled_plugin_path("MV"), legacy)

        fallback = prepare_forge_js(
            "MV",
            source=legacy,
            cfg={"forgeHotkey": "F9", "uiScale": "auto"},
        )
        self.assertIn("Floating launcher disabled", fallback)
        self.assertIn('window.Forge._hotkey = "F9";', fallback)

if __name__ == "__main__":
    unittest.main()
