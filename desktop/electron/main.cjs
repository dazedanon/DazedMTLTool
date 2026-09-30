const {
  clipboard,
  app,
  BrowserWindow,
  ipcMain,
  dialog,
  shell,
} = require("electron");
const { spawn } = require("node:child_process");
const { createInterface } = require("node:readline");
const fs = require("node:fs");
const path = require("node:path");
const { prepareRuntime } = require("./runtime.cjs");
const { ApplicationUpdates, checkReleases } = require("./updates.cjs");
const { findPackage, fileHash } = require("./package-format.cjs");
const { pipeline } = require("node:stream/promises");
const { Readable, Transform } = require("node:stream");
const os = require("node:os");

if (app.isPackaged) app.setName("DazedTL");
if (process.env.DAZEDTL_DESKTOP_PROFILE) {
  const profile = path.resolve(process.env.DAZEDTL_DESKTOP_PROFILE);
  fs.mkdirSync(profile, { recursive: true });
  app.setPath("userData", profile);
}
let runtime,
  runtimeReady,
  runtimeError = "",
  setup;
let updates,
  updateError = "",
  availableRelease = null,
  updateAction = false,
  restarting = null;
const methods = new Set([
  "state",
  "import_project",
  "save_guidance",
  "preview",
  "start",
  "stop",
  "resume",
  "review",
  "export",
  "context",
  "save_context",
  "get_drafts",
  "save_drafts",
  "native_preview",
  "start_native",
  "review_page",
  "apply_reviewed",
  "engine_log",
  "asset_state",
  "asset_open",
  "asset_thumbnails",
  "asset_action",
  "image_list",
  "image_import",
  "image_get",
  "image_save",
  "image_render",
  "image_approve",
  "image_review",
  "image_export",
  "manual_state",
  "batch_state",
  "evaluation_state",
  "evaluation_action",
  "evaluation_draft",
  "evaluation_reasoning",
  "batch_register",
  "batch_action",
  "batch_resume",
  "manual_inspect",
  "manual_start",
  "manual_resume",
  "manual_answer",
  "manual_stop",
  "manual_log",
  "manual_export",
  "instruction_catalog",
  "instruction_get",
  "instruction_save",
  "instruction_draft",
  "instruction_import",
  "guide_catalog",
  "guide_page",
  "settings_transfer",
  "settings_get",
  "settings_save",
  "settings_draft",
  "settings_key",
  "settings_import",
  "settings_models",
  "version_state",
  "version_open",
  "version_save",
  "version_action",
  "len_state",
  "len_open",
  "len_save",
  "len_action",
  "len_documents",
  "len_document_save",
  "workflow_state",
  "workflow_open",
  "workflow_update",
  "workflow_preview",
  "workflow_execute",
  "workflow_stop",
  "workflow_documents",
  "workflow_document_save",
  "workflow_skill",
  "workflow_phase",
  "workflow_draft",
]);
const pending = new Map();
const approvedExports = new Set();
const approvedGuideLinks = new Set();
let backend,
  window,
  serial = 0,
  quitting = false,
  closing = false,
  rendererReady = false,
  closeToken = 0,
  closeTimer;

function backendAlive() {
  return (
    backend?.pid && backend.exitCode === null && backend.signalCode === null
  );
}

async function finishClose() {
  if (quitting) return;
  clearTimeout(closeTimer);
  closeToken = 0;
  if (restarting) {
    try {
      await updates.select(
        restarting.id,
        restarting.revision,
        restarting.rollback,
      );
      const target = await updates.launchTarget();
      process.env.DAZEDTL_DESKTOP_PROFILE = app.getPath("userData");
      process.env.DAZEDTL_UPDATE_TOKEN = target.token;
      app.relaunch({
        execPath: target.executable,
        args: process.argv.slice(1),
      });
    } catch (error) {
      restarting = null;
      closing = false;
      await dialog.showMessageBox(window, {
        type: "error",
        message: "Could not activate this application",
        detail: String(error),
        buttons: ["Keep working"],
      });
      window.webContents.send("workspace:close-cancelled");
      return;
    }
  }
  quitting = true;
  if (setup) setup.kill();
  if (window && !window.isDestroyed()) window.hide();
  if (!backendAlive()) return app.exit(0);
  backend.stdin.end();
  setTimeout(() => {
    backend.kill();
    app.exit(0);
  }, 55000).unref();
}

async function closeFailed(message) {
  clearTimeout(closeTimer);
  closeToken = 0;
  const choice = await dialog.showMessageBox(window, {
    type: "warning",
    title: "Edits could not be saved",
    message: "Keep the app open to preserve your latest edits.",
    detail: message,
    buttons: ["Keep open", "Close without saving"],
    defaultId: 0,
    cancelId: 0,
    noLink: true,
  });
  if (choice.response === 1) finishClose();
  else {
    closing = false;
    restarting = null;
    if (window && !window.isDestroyed())
      window.webContents.send("workspace:close-cancelled");
  }
}

function beginClose() {
  if (closing || quitting) return;
  closing = true;
  if (!rendererReady || !window || window.isDestroyed()) return finishClose();
  closeToken = ++serial;
  closeTimer = setTimeout(() => {
    closeFailed(
      "Saving is taking longer than expected. You can keep working and try closing again.",
    ).catch(() => {
      closing = false;
    });
  }, 10000);
  window.webContents.send("workspace:before-close", closeToken);
}

function failPending(message) {
  for (const { reject } of pending.values()) reject(new Error(message));
  pending.clear();
}

async function request(method, params = {}) {
  await runtimeReady;
  if (runtimeError) throw new Error(runtimeError);
  if (!methods.has(method))
    return Promise.reject(new Error("Unknown desktop operation."));
  if (!backendAlive() || !backend.stdin.writable)
    return Promise.reject(
      new Error("Python service is unavailable. Restart DazedTL."),
    );
  return new Promise((resolve, reject) => {
    const id = ++serial;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(
        new Error("The operation timed out. Check activity before retrying."),
      );
    }, 120000);
    pending.set(id, {
      resolve: (result) => {
        clearTimeout(timer);
        resolve(result);
      },
      reject: (error) => {
        clearTimeout(timer);
        reject(error);
      },
    });
    backend.stdin.write(JSON.stringify({ id, method, params }) + "\n");
  });
}

function trusted(event) {
  if (
    !window ||
    event.sender !== window.webContents ||
    event.senderFrame !== window.webContents.mainFrame
  )
    throw new Error("Untrusted desktop request.");
}

ipcMain.handle("workspace:scale", (event, value) => {
  trusted(event);
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    value < 0.5 ||
    value > 3
  )
    throw new Error("Invalid interface scale.");
  window.webContents.setZoomFactor(value);
});

function startBackend({ root, python, workspace }) {
  const args = ["-u", "-m", "desktop.backend.server", "--workspace", workspace];
  if (process.env.DAZEDTL_DESKTOP_ALLOW_LIVE === "1") args.push("--allow-live");
  if (process.env.DAZEDTL_DESKTOP_PROVIDERS === "1")
    args.push("--production-providers");
  backend = spawn(python, args, {
    cwd: root,
    env: {
      ...process.env,
      PYTHONPATH: root,
      PYTHONNOUSERSITE: "1",
      PYTHONHOME: "",
      PYTHONIOENCODING: "utf-8",
      PYTHONUTF8: "1",
    },
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true,
  });
  createInterface({ input: backend.stdout }).on("line", (line) => {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      return;
    }
    const task = pending.get(message.id);
    if (!task) return;
    pending.delete(message.id);
    if (message.error) task.reject(new Error(message.error));
    else task.resolve(message.result);
  });
  // Never forward child stderr or credentials into the renderer.
  backend.stderr.on("data", () => {});
  backend.stdin.on("error", () =>
    failPending(
      "The Python connection closed. Unfinished requests were not retried.",
    ),
  );
  backend.on("error", () =>
    failPending("Could not start the Python service. Check DAZEDTL_PYTHON."),
  );
  backend.on("exit", () => {
    failPending("The Python service stopped. Completed work is saved.");
    if (quitting) app.exit(0);
    else if (window && !window.isDestroyed())
      window.webContents.send(
        "workspace:service-stopped",
        "The Python service stopped. Restart the app to recover saved work.",
      );
  });
}

if (!app.requestSingleInstanceLock()) app.exit(0);
app.on("second-instance", () => {
  if (window) {
    window.show();
    window.focus();
  }
});
app.whenReady().then(async () => {
  if (app.isPackaged) {
    try {
      updates = new ApplicationUpdates(
        app.getPath("userData"),
        await findPackage(process.execPath),
      );
      const target = await updates.launchTarget(
        process.env.DAZEDTL_UPDATE_TOKEN || "",
      );
      delete process.env.DAZEDTL_UPDATE_TOKEN;
      if (!target.current) {
        process.env.DAZEDTL_DESKTOP_PROFILE = app.getPath("userData");
        process.env.DAZEDTL_UPDATE_TOKEN = target.token;
        app.relaunch({
          execPath: target.executable,
          args: process.argv.slice(1),
        });
        app.exit(0);
        return;
      }
    } catch (error) {
      updateError = String(error);
      updates = null;
    }
  }
  runtimeReady = prepareRuntime({
    packaged: app.isPackaged,
    resources: process.resourcesPath,
    profile: app.getPath("userData"),
    onProcess: (child) => {
      setup = child;
    },
  })
    .then((value) => {
      runtime = value;
      if (!quitting) startBackend(value);
    })
    .catch((error) => {
      runtimeError = String(error);
    });
  window = new BrowserWindow({
    width: 1380,
    height: 940,
    minWidth: 900,
    minHeight: 650,
    title: "DazedTL · Desktop preview",
    backgroundColor: "#171a20",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      // Translation progress and approval prompts must remain responsive
      // while the user works in a game or editor beside this window.
      backgroundThrottling: false,
    },
  });
  window.setMenuBarVisibility(false);
  window.on("close", (event) => {
    if (!quitting) {
      event.preventDefault();
      beginClose();
    }
  });
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event) => event.preventDefault());
  window.webContents.session.setPermissionRequestHandler(
    (_contents, _permission, callback) => callback(false),
  );
  ipcMain.handle("workspace:ready", async (event) => {
    trusted(event);
    rendererReady = true;
    if (updates) await updates.healthy();
    if (process.env.DAZEDTL_DESKTOP_METRICS_FILE) {
      fs.writeFileSync(
        process.env.DAZEDTL_DESKTOP_METRICS_FILE,
        JSON.stringify({ ready: true }),
      );
      setTimeout(() => app.quit(), 3000);
    }
  });
  ipcMain.handle("workspace:runtime", async (event) => {
    trusted(event);
    await runtimeReady;
    if (runtimeError) throw new Error(runtimeError);
    return {
      packaged: app.isPackaged,
      root: runtime.root,
      python: runtime.python,
      workspace: runtime.workspace,
    };
  });
  ipcMain.on("workspace:close-ready", (event, reply) => {
    trusted(event);
    if (!closing || !closeToken || reply?.token !== closeToken) return;
    if (reply.error)
      closeFailed(String(reply.error).slice(0, 1000)).catch(() => {
        closing = false;
      });
    else finishClose();
  });
  ipcMain.handle("workspace:call", async (event, method, params) => {
    trusted(event);
    // Drain any already queued work before checking activity. Once restart is
    // requested, only draft persistence and read operations may reach Python.
    if (
      restarting &&
      !/_(state|draft|documents|catalog|get|log)$/.test(method) &&
      ![
        "state",
        "save_drafts",
        "len_save",
        "version_save",
        "image_save",
      ].includes(method)
    )
      throw new Error(
        "The application is preparing to restart. Finish saving first.",
      );
    const result = await request(method, params);
    if (method === "guide_page")
      for (const url of result.external_links || [])
        approvedGuideLinks.add(url);
    if (method === "settings_transfer" && result.path)
      approvedExports.add(result.path);
    if (
      method === "export" ||
      method === "image_export" ||
      method === "manual_export"
    )
      approvedExports.add(result.path);
    if (
      method === "len_state" ||
      method === "len_open" ||
      method === "asset_open" ||
      method === "evaluation_state" ||
      method === "asset_state"
    )
      for (const target of Object.values(result.paths || {}))
        approvedExports.add(target);
    return result;
  });
  ipcMain.handle("workspace:updates", async (event, action, options = {}) => {
    trusted(event);
    if (action === "state")
      return {
        packaged: app.isPackaged,
        error: updateError,
        application: updates ? await updates.state() : null,
        release: availableRelease,
      };
    if (action === "check") {
      availableRelease = await checkReleases();
      return availableRelease;
    }
    if (!updates)
      throw new Error(
        updateError ||
          "Application updates are available in a packaged build. Rebuild this source checkout to update it.",
      );
    if (updateAction || closing)
      throw new Error("Wait for the current application update action.");
    updateAction = true;
    try {
      if (action === "import") {
        const selected = await dialog.showOpenDialog(window, {
          title: "Choose an extracted DazedTL desktop package",
          properties: ["openDirectory"],
        });
        if (selected.canceled) return null;
        return await updates.stage(selected.filePaths[0]);
      }
      if (action === "download") {
        if (!availableRelease)
          throw new Error("Check for a compatible desktop release first.");
        const release = { ...availableRelease };
        if (
          !Number.isSafeInteger(release.bytes) ||
          release.bytes < 1 ||
          release.bytes > 2 * 1024 ** 3
        )
          throw new Error("The release archive has an invalid size.");
        await runtimeReady;
        const temporary = await fs.promises.mkdtemp(
          path.join(os.tmpdir(), "dazedtl-update-"),
        );
        try {
          const archive = path.join(temporary, "application.tar.gz");
          const response = await fetch(release.url, {
            signal: AbortSignal.timeout(600000),
          });
          if (!response.ok || !response.body)
            throw new Error("Could not download the selected release.");
          let bytes = 0;
          const limit = new Transform({
            transform(chunk, _encoding, callback) {
              bytes += chunk.length;
              callback(
                bytes > release.bytes
                  ? new Error("The release archive exceeded its expected size.")
                  : null,
                chunk,
              );
            },
          });
          await pipeline(
            Readable.fromWeb(response.body),
            limit,
            fs.createWriteStream(archive, { flags: "wx" }),
          );
          if (
            bytes !== release.bytes ||
            (await fileHash(archive)) !== release.sha256
          )
            throw new Error(
              "The downloaded release checksum did not match. Nothing was installed.",
            );
          const extracted = path.join(temporary, "application");
          await new Promise((resolve, reject) => {
            const child = spawn(
              runtime.python,
              [
                "-I",
                path.join(runtime.root, "desktop/backend/package_archive.py"),
                "extract",
                archive,
                extracted,
              ],
              { windowsHide: true, stdio: "ignore" },
            );
            child.once("error", reject);
            child.once("exit", (code) =>
              code === 0
                ? resolve()
                : reject(
                    new Error(
                      "The desktop archive could not be unpacked safely.",
                    ),
                  ),
            );
          });
          return await updates.stage(extracted);
        } finally {
          await fs.promises.rm(temporary, { recursive: true, force: true });
        }
      }
      if (action === "activate" || action === "rollback") {
        restarting = {
          id: options.id,
          revision: options.revision,
          rollback: action === "rollback",
        };
        try {
          const state = await request("state");
          if (state.active_job)
            throw new Error(
              "Finish or stop the active translation or tool action before restarting.",
            );
          beginClose();
          return { restarting: true };
        } catch (error) {
          restarting = null;
          throw error;
        }
      }
      throw new Error("Unknown application update action.");
    } finally {
      updateAction = false;
    }
  });
  ipcMain.handle("workspace:copy-text", (event, text) => {
    trusted(event);
    if (typeof text !== "string" || Buffer.byteLength(text, "utf8") > 2_000_000)
      throw new Error("Copy text must be below 2 MB.");
    clipboard.writeText(text);
  });
  ipcMain.handle("workspace:choose", async (event) => {
    trusted(event);
    const selected = await dialog.showOpenDialog(window, {
      title: "Choose a source game folder",
      properties: ["openDirectory"],
    });
    return selected.canceled ? null : selected.filePaths[0];
  });
  ipcMain.handle("workspace:guide-link", async (event, url) => {
    trusted(event);
    if (!approvedGuideLinks.has(url) || !/^https?:\/\//.test(url))
      throw new Error("Choose a link from the built-in guide.");
    await shell.openExternal(url);
  });
  ipcMain.handle("workspace:configuration-file", async (event, kind) => {
    trusted(event);
    const filters =
      kind === "instruction"
        ? [{ name: "Shared instructions", extensions: ["md", "txt", "json"] }]
        : kind === "settings"
          ? [
              { name: "DazedTL settings", extensions: ["json", "env"] },
              { name: "All files", extensions: ["*"] },
            ]
          : null;
    if (!filters) throw new Error("Choose a configuration file type.");
    const selected = await dialog.showOpenDialog(window, {
      title: "Import " + kind,
      properties: ["openFile", "showHiddenFiles"],
      filters,
    });
    return selected.canceled ? null : selected.filePaths[0];
  });
  ipcMain.handle("workspace:evaluation-file", async (event, kind) => {
    trusted(event);
    const extensions = {
      archive: ["dazedeval", "zip"],
      review: ["csv"],
      calibration: ["json"],
    }[kind];
    if (!extensions) throw new Error("Choose an evaluation file type.");
    const selected = await dialog.showOpenDialog(window, {
      title: "Choose evaluation " + kind,
      properties: ["openFile"],
      filters: [{ name: "Evaluation " + kind, extensions }],
    });
    return selected.canceled ? null : selected.filePaths[0];
  });
  ipcMain.handle("workspace:open-export", async (event, target) => {
    trusted(event);
    if (!approvedExports.has(target))
      throw new Error("Build this data test copy before opening it.");
    return shell.openPath(target);
  });
  ipcMain.handle("workspace:image", async (event) => {
    trusted(event);
    const selected = await dialog.showOpenDialog(window, {
      title: "Choose an image to edit",
      properties: ["openFile"],
      filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg", "webp"] }],
    });
    if (selected.canceled) return null;
    const target = selected.filePaths[0];
    if (fs.statSync(target).size > 20 * 1024 * 1024)
      throw new Error("Choose an image below 20 MB.");
    const extension = path.extname(target).toLowerCase();
    const mime = {
      ".png": "image/png",
      ".jpg": "image/jpeg",
      ".jpeg": "image/jpeg",
      ".webp": "image/webp",
    }[extension];
    if (!mime) throw new Error("Unsupported image format.");
    return {
      name: path.basename(target),
      source_path: target,
      url: `data:${mime};base64,${fs.readFileSync(target).toString("base64")}`,
    };
  });
  window.loadFile(path.join(__dirname, "../dist/index.html"));
});
app.on("window-all-closed", () => app.quit());
app.on("before-quit", (event) => {
  if (!quitting) {
    event.preventDefault();
    beginClose();
  }
});
