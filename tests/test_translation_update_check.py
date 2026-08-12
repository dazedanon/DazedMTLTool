"""Regression coverage for the fail-open RPG Maker update warning."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from util.translation_update_check.installer import PLUGIN_NAME, install


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PATH = ROOT / "gameupdate" / "gameupdate" / f"{PLUGIN_NAME}.js"


class TranslationUpdateCheckInstallerTests(unittest.TestCase):
    def test_installs_once_for_mv_and_mz(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            for engine, relative in (
                ("MV", Path("www/js")),
                ("MZ", Path("js")),
            ):
                with self.subTest(engine=engine):
                    game = base / engine
                    js_dir = game / relative
                    js_dir.mkdir(parents=True)
                    plugins_js = js_dir / "plugins.js"
                    plugins_js.write_text("var $plugins =\n[\n];\n", encoding="utf-8")

                    self.assertTrue(install(game)[0])
                    self.assertTrue(install(game)[0])

                    content = plugins_js.read_text(encoding="utf-8")
                    self.assertEqual(content.count(f'"name": "{PLUGIN_NAME}"'), 1)
                    self.assertEqual(
                        (js_dir / "plugins" / f"{PLUGIN_NAME}.js").read_bytes(),
                        PLUGIN_PATH.read_bytes(),
                    )

    def test_invalid_plugin_list_is_left_unchanged(self):
        with tempfile.TemporaryDirectory() as raw:
            game = Path(raw)
            js_dir = game / "js"
            js_dir.mkdir()
            plugins_js = js_dir / "plugins.js"
            original = "var $plugins = not_an_array;\n"
            plugins_js.write_text(original, encoding="utf-8")

            ok, _message = install(game)

            self.assertFalse(ok)
            self.assertEqual(plugins_js.read_text(encoding="utf-8"), original)
            self.assertFalse((js_dir / "plugins" / f"{PLUGIN_NAME}.js").exists())


@unittest.skipUnless(shutil.which("node"), "Node.js is required for the plugin runtime contract")
class TranslationUpdateCheckRuntimeTests(unittest.TestCase):
    def test_warning_and_fail_open_contract(self):
        harness = textwrap.dedent(
            """
            const vm = require("vm");
            const path = require("path");
            const EventEmitter = require("events");
            const plugin = process.argv[1];
            const source = require("fs").readFileSync(plugin, "utf8");

            function runCase(options) {
              return new Promise((resolve) => {
                const alerts = [];
                const links = [];
                const opened = [];
                const buttons = [];
                const writes = [];
                function makeElement(tag) {
                  const element = {
                    tagName: tag.toUpperCase(), style: {}, children: [], parentNode: null,
                    appendChild(child) {
                      child.parentNode = this;
                      this.children.push(child);
                      if (child.tagName === "A") links.push(child);
                      if (child.tagName === "BUTTON") buttons.push(child);
                    },
                    removeChild(child) {
                      this.children = this.children.filter((item) => item !== child);
                      child.parentNode = null;
                    },
                    addEventListener(name, callback) { this["on" + name] = callback; }
                  };
                  return element;
                }
                const fakeFs = {
                  statSync(file) {
                    if (file === "/game/gameupdate/patch-config.txt") {
                      return { isFile() { return true; } };
                    }
                    throw new Error("missing");
                  },
                  readFileSync(file) {
                    if (file.endsWith("patch-config.txt")) {
                      return "forge=github\\nhost=github.com\\nusername=owner\\nrepo=patch\\nbranch=main\\n";
                    }
                    if (file.endsWith("previous_patch_sha.txt")) {
                      if (options.missingState) throw new Error("missing state");
                      return options.installed;
                    }
                    throw new Error("unexpected file");
                  },
                  writeFileSync(file, value, encoding) {
                    writes.push({ file, value, encoding });
                  }
                };
                const fakeHttps = {
                  get(requestOptions, callback) {
                    const request = new EventEmitter();
                    request.setTimeout = function() {};
                    request.destroy = function() {};
                    process.nextTick(() => {
                      if (options.networkError) {
                        request.emit("error", new Error("offline"));
                        return;
                      }
                      const response = new EventEmitter();
                      response.statusCode = 200;
                      response.setEncoding = function() {};
                      response.resume = function() {};
                      callback(response);
                      response.emit("data", JSON.stringify({ sha: options.latest }));
                      response.emit("end");
                    });
                    return request;
                  }
                };
                const context = {
                  require(name) {
                    if (name === "fs") return fakeFs;
                    if (name === "path") return path.posix;
                    if (name === "https") return fakeHttps;
                    throw new Error("unexpected module");
                  },
                  process: { cwd() { return "/game"; }, execPath: "/game/Game.exe" },
                  location: { pathname: "/game/index.html" },
                  window: {
                    alert(message) { alerts.push(message); },
                    open(url) { opened.push(url); },
                    confirm() { return options.confirmManual !== false; }
                  },
                  setTimeout(callback) { callback(); }
                };
                if (options.withDocument) {
                  context.document = { body: makeElement("body"), createElement: makeElement };
                }
                let thrown = null;
                try { vm.runInNewContext(source, context); }
                catch (error) { thrown = String(error); }
                setImmediate(() => {
                  if (options.clickLink && links[0] && links[0].onclick) {
                    links[0].onclick({ preventDefault() {} });
                  }
                  if (options.confirmInstalled) {
                    const button = buttons.find((item) =>
                      item.textContent === "I installed this update manually");
                    if (button && button.onclick) button.onclick();
                  }
                  resolve({
                    alerts: alerts.length,
                    links: links.map((link) => link.href),
                    opened,
                    writes,
                    thrown
                  });
                });
              });
            }

            (async function() {
              const oldSha = "a".repeat(40);
              const newSha = "b".repeat(40);
              const results = {
                outdated: await runCase({
                  installed: oldSha, latest: newSha, withDocument: true, clickLink: true
                }),
                manuallyInstalled: await runCase({
                  installed: oldSha, latest: newSha, withDocument: true,
                  confirmInstalled: true
                }),
                current: await runCase({ installed: newSha, latest: newSha }),
                offline: await runCase({ installed: oldSha, latest: newSha, networkError: true }),
                missingState: await runCase({ latest: newSha, missingState: true })
              };
              process.stdout.write(JSON.stringify(results));
            })().catch((error) => { console.error(error); process.exit(1); });
            """
        )

        completed = subprocess.run(
            [shutil.which("node"), "-e", harness, str(PLUGIN_PATH)],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        results = json.loads(completed.stdout)

        self.assertEqual(
            results["outdated"],
            {
                "alerts": 0,
                "links": ["https://github.com/owner/patch"],
                "opened": ["https://github.com/owner/patch"],
                "writes": [],
                "thrown": None,
            },
        )
        self.assertEqual(
            results["manuallyInstalled"],
            {
                "alerts": 0,
                "links": ["https://github.com/owner/patch"],
                "opened": [],
                "writes": [
                    {
                        "file": "/game/gameupdate/previous_patch_sha.txt",
                        "value": "b" * 40 + "\n",
                        "encoding": "ascii",
                    }
                ],
                "thrown": None,
            },
        )
        for name in ("current", "offline", "missingState"):
            with self.subTest(name=name):
                self.assertEqual(
                    results[name],
                    {
                        "alerts": 0,
                        "links": [],
                        "opened": [],
                        "writes": [],
                        "thrown": None,
                    },
                )
