// Native update acceptance: temporary packages/profile, fake credentials, no provider requests.
const { _electron: electron, chromium, expect } = require("@playwright/test");
const fs = require("node:fs"),
  fsp = fs.promises,
  path = require("node:path"),
  os = require("node:os"),
  net = require("node:net");
const { execFileSync } = require("node:child_process");
const repository = path.resolve(__dirname, "../.."),
  desktop = path.join(repository, "desktop");
const python =
  process.env.DAZEDTL_BUILD_PYTHON ||
  path.join(
    repository,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
const resourcesRelative =
  process.platform === "darwin"
    ? "DazedTL.app/Contents/Resources"
    : "resources";
const format = require(path.join(desktop, "electron/package-format.cjs"));
(async () => {
  const result = JSON.parse(
      fs.readFileSync(path.join(desktop, "out/package-result.json")),
    ),
    root = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-updater-native-"));
  const candidate = path.join(root, "candidate"),
    profile = path.join(root, "profile"),
    workspace = path.join(profile, "workspace");
  const errors = [],
    requests = [];
  let app, browser, page, port;
  const server = net.createServer();
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  port = server.address().port;
  await new Promise((r) => server.close(r));
  const env = {
    ...process.env,
    DAZEDTL_DESKTOP_PROFILE: profile,
    DAZEDTL_DESKTOP_ALLOW_LIVE: "0",
    DAZEDTL_DESKTOP_PROVIDERS: "0",
    DAZEDTL_TEST_OFFLINE: "1",
  };
  delete env.DAZEDTL_DESKTOP_WORKSPACE;
  delete env.ELECTRON_RUN_AS_NODE;
  function watch(p) {
    p.on("pageerror", (e) => errors.push(e.message));
    p.on("request", (r) => {
      if (/^https?:/.test(r.url())) requests.push(r.url());
    });
  }
  async function reconnect(expected) {
    const deadline = Date.now() + 40000;
    while (Date.now() < deadline) {
      try {
        browser = await chromium.connectOverCDP("http://127.0.0.1:" + port, {
          timeout: 1000,
        });
        page = browser.contexts()[0].pages()[0];
        watch(page);
        await expect(page.getByText("Python service connected")).toBeVisible({
          timeout: 15000,
        });
        const state = await page.evaluate(() =>
          window.workspace.updates("state"),
        );
        if (
          state.application?.current.id === expected &&
          !state.application.pending
        )
          return state;
        await browser.close();
        browser = null;
      } catch (e) {
        if (browser) {
          await browser.close().catch(() => {});
          browser = null;
        }
      }
      await new Promise((r) => setTimeout(r, 150));
    }
    throw Error("Relaunched application did not become ready");
  }
  try {
    execFileSync(python, [
      path.join(desktop, "backend/package_archive.py"),
      "extract",
      result.archive,
      candidate,
    ]);
    const base = await format.readManifest(candidate, true);
    execFileSync(python, [
      "-c",
      `import hashlib,json,sys\nfrom pathlib import Path\np=Path(sys.argv[1]);b=p/sys.argv[2]/'backend';f=b/'data/skills/system.md';f.write_text(f.read_text(encoding='utf-8')+'\\nNative update fixture.\\n',encoding='utf-8');m=json.loads((b/'runtime-manifest.json').read_text(encoding='utf-8'));v=m['files']['data/skills/system.md'];v.update(sha256=hashlib.sha256(f.read_bytes()).hexdigest(),bytes=f.stat().st_size);m['bundle_id']=hashlib.sha256(json.dumps(m['files'],sort_keys=True).encode()).hexdigest();(b/'runtime-manifest.json').write_text(json.dumps(m),encoding='utf-8');r=json.loads((p/sys.argv[2]/'runtime.json').read_text(encoding='utf-8'));r['backend_bundle']=m['bundle_id'];(p/sys.argv[2]/'runtime.json').write_text(json.dumps(r),encoding='utf-8')`,
      candidate,
      resourcesRelative,
    ]);
    const { id, files, ...metadata } = base;
    metadata.version = "0.1.0-update-fixture";
    const next = await format.createManifest(candidate, metadata);
    app = await electron.launch({
      executablePath: result.executable,
      env,
      args: [],
    });
    page = await app.firstWindow();
    watch(page);
    await expect(page.getByText("Python service connected")).toBeVisible();
    await page.evaluate(async () => {
      const settings = await window.workspace.settingsGet();
      settings.values.width = 67;
      await window.workspace.settingsSave({
        revision: settings.revision,
        values: settings.values,
        engines: settings.engines,
      });
      await window.workspace.settingsKey({
        action: "save",
        name: "Update fixture",
        secret: "fixture-secret-never-sent",
        endpoint: "http://127.0.0.1:9",
      });
      const instruction =
        await window.workspace.instructionGet("skills/system.md");
      await window.workspace.instructionSave({
        name: "skills/system.md",
        revision: instruction.revision,
        text: "Preserved profile instructions.",
      });
    });
    const savedFiles = [
      "settings/settings.json",
      "settings/api_keys.json",
      "shared-data/skills/system.md",
    ];
    const saved = Object.fromEntries(
      savedFiles.map((f) => [f, fs.readFileSync(path.join(workspace, f))]),
    );
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Updates & rollback", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Updates & rollback", exact: true }),
    ).toBeVisible();
    await app.evaluate(({ dialog }, folder) => {
      dialog.showOpenDialog = async () => ({
        canceled: false,
        filePaths: [folder],
      });
      global.fetch = async () => ({ ok: true, json: async () => [] });
    }, candidate);
    await page
      .getByRole("button", { name: "Check for updates", exact: true })
      .click();
    await expect(
      page.getByText("No compatible desktop release has been published."),
    ).toBeVisible();
    await format.readManifest(candidate, true);
    console.log("Candidate verified before import");
    await page
      .getByRole("button", { name: "Import extracted package", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Activate and restart", exact: true }),
    ).toBeEnabled({ timeout: 30000 });
    fs.mkdirSync(path.join(repository, ".tmp-ui/desktop-evidence"), {
      recursive: true,
    });
    await page.screenshot({
      path: path.join(
        repository,
        ".tmp-ui/desktop-evidence/application-updates.png",
      ),
      fullPage: true,
    });
    await app.evaluate(({ app }, port) => {
      const relaunch = app.relaunch.bind(app);
      app.relaunch = (options) =>
        relaunch({
          ...options,
          args: [
            ...options.args.filter(
              (v) => !v.startsWith("--remote-debugging-port"),
            ),
            "--remote-debugging-port=" + port,
          ],
        });
    }, port);
    await page
      .getByRole("button", { name: "Activate and restart", exact: true })
      .click();
    await new Promise((r) => app.once("close", r));
    app = null;
    let state = await reconnect(next.id);
    expect(
      fs.readFileSync(path.join(profile, "tool/data/skills/system.md"), "utf8"),
    ).toContain("Native update fixture.");
    for (const f of savedFiles)
      expect(fs.readFileSync(path.join(workspace, f)).equals(saved[f])).toBe(
        true,
      );
    expect(state.application.previous.id).toBe(base.id);
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Updates & rollback", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Roll back and restart", exact: true }),
    ).toBeEnabled();
    await page
      .getByRole("button", { name: "Roll back and restart", exact: true })
      .click();
    await new Promise((r) => browser.once("disconnected", r));
    browser = null;
    state = await reconnect(base.id);
    expect(
      fs.readFileSync(path.join(profile, "tool/data/skills/system.md"), "utf8"),
    ).not.toContain("Native update fixture.");
    for (const f of savedFiles)
      expect(fs.readFileSync(path.join(workspace, f)).equals(saved[f])).toBe(
        true,
      );
    expect(state.application.previous.id).toBe(next.id);
    await page.evaluate(() => window.close());
    await new Promise((r) => browser.once("disconnected", r));
    browser = null;
    await format.readManifest(result.packages[0], true);
    expect(errors).toEqual([]);
    expect(requests).toEqual([]);
    console.log(
      "PASS: actual packaged import → restart into staged app → healthy acknowledgement → rollback/restart; shipped defaults change and restore; settings, vault and profile instructions unchanged; original package stays byte-for-byte valid; no provider or external HTTP calls.",
    );
  } finally {
    if (app) await app.close().catch(() => {});
    if (browser) {
      await browser
        .contexts()[0]
        .pages()[0]
        ?.evaluate(() => window.close())
        .catch(() => {});
      await browser.close().catch(() => {});
    }
    fs.rmSync(root, { recursive: true, force: true });
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
