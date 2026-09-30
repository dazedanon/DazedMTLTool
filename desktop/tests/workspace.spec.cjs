const { test, expect, _electron: electron } = require("@playwright/test");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

test("isolated sample survives navigation and reaches reviewed data export", async () => {
  const temporary = fs.mkdtempSync(
    path.join(os.tmpdir(), "dazedtl-desktop-e2e-"),
  );
  const source = path.join(temporary, "Sample Game");
  fs.mkdirSync(path.join(source, "data"), { recursive: true });
  fs.mkdirSync(path.join(source, "js"));
  const original = JSON.stringify([
    null,
    { id: 1, name: "薬", description: "体力を回復する。", note: "保持する。" },
  ]);
  fs.writeFileSync(path.join(source, "data", "Items.json"), original);
  fs.writeFileSync(path.join(source, "data", "System.json"), "{}");
  fs.writeFileSync(path.join(source, "js", "plugins.js"), "var $plugins = [];");
  const sourceImage = path.join(temporary, "menu.png");
  execFileSync(
    process.env.DAZEDTL_PYTHON ||
      path.resolve(
        __dirname,
        process.platform === "win32"
          ? "../../.venv/Scripts/python.exe"
          : "../../.venv/bin/python",
      ),
    [
      "-c",
      "from PIL import Image, ImageDraw; import sys; im=Image.new('RGBA',(320,160),'#20242c'); ImageDraw.Draw(im).text((90,65),'START',fill='white'); im.save(sys.argv[1])",
      sourceImage,
    ],
  );
  const originalImage = fs.readFileSync(sourceImage);
  const env = {
    ...process.env,
    DAZEDTL_DESKTOP_WORKSPACE: path.join(temporary, "workspace"),
    DAZEDTL_DESKTOP_PROFILE: path.join(temporary, "profile"),
    DAZEDTL_DESKTOP_ALLOW_LIVE: "0",
    DAZEDTL_DESKTOP_PROVIDERS: "0",
    TIKTOKEN_CACHE_DIR: path.join(temporary, "empty-token-cache"),
  };
  delete env.ELECTRON_RUN_AS_NODE;
  const started = performance.now();
  let application;
  try {
    const launchOptions = {
      executablePath:
        process.env.DAZEDTL_PACKAGED_APP ||
        process.env.DAZEDTL_ELECTRON ||
        undefined,
      args: [
        ...(process.env.DAZEDTL_PACKAGED_APP
          ? []
          : [path.resolve(__dirname, "..")]),
        ...(process.env.DAZEDTL_HEADLESS === "1"
          ? ["--ozone-platform=headless", "--disable-gpu"]
          : []),
      ],
      env,
    };
    application = await electron.launch(launchOptions);
    const page = await application.firstWindow();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await expect(page.getByText("Python service connected")).toBeVisible();
    const runtime = await page.evaluate(() => window.workspace.runtime());
    expect(runtime.packaged).toBe(!!process.env.DAZEDTL_PACKAGED_APP);
    if (runtime.packaged) {
      expect(runtime.root.startsWith(path.join(temporary, "profile"))).toBe(
        true,
      );
      expect(runtime.python.startsWith(path.join(temporary, "profile"))).toBe(
        true,
      );
      expect(
        fs.existsSync(
          path.join(
            runtime.root,
            "data",
            "skills",
            "game-translation",
            "SKILL.md",
          ),
        ),
      ).toBe(true);
      expect(fs.existsSync(path.join(runtime.root, ".env"))).toBe(false);
      expect(
        fs.existsSync(path.join(runtime.root, "data", "api_keys.json")),
      ).toBe(false);
    }
    const readyMs = performance.now() - started;
    // Settings work before any game is imported, and secrets never come back
    // through the renderer API. The endpoint is a generated offline fixture.
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Settings", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Set up your translation tools." }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Add credential", exact: true })
      .click();
    await page
      .getByLabel("Credential name", { exact: true })
      .fill("Offline fixture");
    await page
      .getByLabel("API secret", { exact: true })
      .fill("ui-fixture-secret");
    await page
      .getByLabel("Credential endpoint", { exact: true })
      .fill("https://provider.example.test/v1");
    await page
      .getByRole("button", { name: "Save credential", exact: true })
      .click();
    await expect(
      page.getByText("Credential saved.", { exact: true }),
    ).toBeVisible();
    const settingsReply = await page.evaluate(() =>
      window.workspace.settingsGet(),
    );
    expect(JSON.stringify(settingsReply)).not.toContain("ui-fixture-secret");
    await page
      .getByLabel("Target language", { exact: true })
      .fill("English fixture");
    await page
      .getByRole("button", { name: "Save settings", exact: true })
      .first()
      .click();
    await expect(
      page.getByText("Settings saved. New runs will use these values.", {
        exact: true,
      }),
    ).toBeVisible();
    await page.getByRole("button", { name: "CSV", exact: true }).click();
    await page.getByLabel("Source column", { exact: true }).fill("3");
    await page
      .getByRole("button", { name: "Save settings", exact: true })
      .first()
      .click();
    await expect(
      page.getByText("Settings saved. New runs will use these values.", {
        exact: true,
      }),
    ).toBeVisible();
    expect(
      (await page.evaluate(() => window.workspace.settingsGet())).engines.csv
        .SOURCE_COLUMN,
    ).toBe(2);
    await page.getByRole("button", { name: "General", exact: true }).click();
    await page
      .getByLabel("Target language", { exact: true })
      .fill("Unsaved language draft");
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Overview", exact: true })
      .click();

    await page.getByLabel("Game folder", { exact: true }).fill(source);
    await page.getByLabel("Read the original Git branch").uncheck();
    await page.getByRole("button", { name: "Open isolated workspace" }).click();
    await expect(
      page.getByRole("heading", { name: "Translate with context." }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Text sample", exact: true })
      .click();
    await page.locator(".text-row input").first().check();
    await page
      .getByRole("button", { name: "Preview run", exact: true })
      .click();
    await expect(page.getByText("$0.00 maximum reserved")).toBeVisible();
    await page.getByRole("button", { name: "Start offline test" }).click();
    await expect(page.locator(".jobbar")).toContainText(
      "Complete · 1/1 entries",
    );
    const navigationStart = performance.now();
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Review & test" })
      .click();
    await expect(
      page.getByRole("heading", { name: "Make every line count." }),
    ).toBeVisible();
    const navigationMs = performance.now() - navigationStart;
    await page.getByLabel("English translation").fill("Restores health.");
    await page.getByRole("button", { name: "Save & approve" }).click();
    await expect(page.getByText("1 of 1 entries reviewed")).toBeVisible();
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Release", exact: true })
      .click();
    await page.getByRole("button", { name: "Build data test copy" }).click();
    await expect(page.locator(".output-path")).toBeVisible();
    const target = await page.locator(".output-path").innerText();
    expect(
      fs.readFileSync(path.join(source, "data", "Items.json"), "utf8"),
    ).toBe(original);
    expect(
      JSON.parse(
        fs.readFileSync(path.join(target, "data", "Items.json"), "utf8"),
      )[1].description,
    ).toBe("Restores health.");
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Images", exact: true })
      .click();
    await expect(page.locator("canvas")).toBeVisible();
    if (
      await page
        .getByRole("button", { name: "Close activity", exact: true })
        .isVisible()
    )
      await page
        .getByRole("button", { name: "Close activity", exact: true })
        .click();
    // Only the native file chooser is replaced. Image persistence, rendering,
    // approval and export use the real Python service and existing renderer.
    await application.evaluate(
      ({ ipcMain }, image) => {
        ipcMain.removeHandler("workspace:image");
        ipcMain.handle("workspace:image", () => image);
      },
      {
        name: "menu.png",
        source_path: sourceImage,
        url: `data:image/png;base64,${originalImage.toString("base64")}`,
      },
    );
    await page
      .getByRole("button", { name: "Open image…", exact: true })
      .click();
    await expect(page.getByText("320 × 160 pixels")).toBeVisible();
    await page.getByRole("button", { name: "Add region", exact: true }).click();
    const canvas = page.locator("canvas");
    const rect = await canvas.boundingBox();
    const scrollBeforeDraw = await page
      .locator(".workspace")
      .evaluate((element) => element.scrollTop);
    await page.mouse.move(
      rect.x + rect.width / 2 - 90,
      rect.y + rect.height / 2 - 30,
    );
    await page.mouse.down();
    await page.mouse.move(
      rect.x + rect.width / 2 + 90,
      rect.y + rect.height / 2 + 30,
    );
    await page.mouse.up();
    expect(
      await page.locator(".workspace").evaluate((element) => element.scrollTop),
    ).toBe(scrollBeforeDraw);
    await expect(
      page.getByLabel("Translated image text", { exact: true }),
    ).toBeVisible({ timeout: 3000 });
    await page
      .getByLabel("Translated image text", { exact: true })
      .fill("Begin adventure");
    await page.getByLabel("Image background treatment").selectOption("solid");
    const geometry = () =>
      page
        .locator(".pixel-fields input[type=number]")
        .evaluateAll((inputs) =>
          inputs.slice(0, 4).map((input) => input.value),
        );
    const originalBox = await geometry();
    await page
      .getByRole("slider", { name: "Image zoom", exact: true })
      .fill("200");
    await application.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].setSize(1200, 900),
    );
    expect(await geometry()).toEqual(originalBox);
    await page.getByRole("button", { name: "Select", exact: true }).click();
    await canvas.focus();
    await page.keyboard.press("ArrowRight");
    expect(await geometry()).not.toEqual(originalBox);
    await page
      .getByRole("button", { name: "Undo image edit", exact: true })
      .click();
    expect(await geometry()).toEqual(originalBox);
    await page
      .getByRole("button", { name: "Render preview", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Approve preview", exact: true }),
    ).toBeEnabled();
    await page
      .getByRole("button", { name: "Approve preview", exact: true })
      .click();
    await page.getByRole("button", { name: "Export PNG", exact: true }).click();
    await expect(page.locator(".image-output-path")).toBeVisible();
    const imageOutput = await page.locator(".image-output-path").innerText();
    expect(fs.readFileSync(path.join(imageOutput, "menu.png"))).not.toEqual(
      originalImage,
    );
    expect(fs.readFileSync(sourceImage)).toEqual(originalImage);
    const layout = await page.evaluate(() => ({
      width: innerWidth,
      scroll: document.documentElement.scrollWidth,
      isolation:
        typeof window.require === "undefined" &&
        typeof window.process === "undefined",
    }));
    expect(layout.scroll).toBeLessThanOrEqual(layout.width);
    expect(layout.isolation).toBe(true);
    const metrics = await application.evaluate(({ app }) =>
      app.getAppMetrics().map((p) => ({
        type: p.type,
        memory: p.memory,
        cpu: p.cpu.percentCPUUsage,
      })),
    );
    const evidence = path.resolve(__dirname, "../../.tmp-ui/desktop-evidence");
    fs.mkdirSync(evidence, { recursive: true });
    await page.screenshot({
      path: path.join(evidence, "canvas.png"),
      fullPage: true,
    });
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Translate", exact: true })
      .click();
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Images", exact: true })
      .click();
    await expect(
      page.getByLabel("Translated image text", { exact: true }),
    ).toHaveValue("Begin adventure");
    expect(await geometry()).toEqual(originalBox);
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Translate", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Preview run", exact: true })
      .click();
    await page.getByRole("button", { name: "Start offline test" }).click();
    const textRuns = page.locator(".job-row").filter({
      has: page.getByRole("button", { name: "Review this run", exact: true }),
    });
    await expect(textRuns).toHaveCount(2);
    await page
      .locator(".job-row")
      .filter({
        has: page.getByRole("button", { name: "Review this run", exact: true }),
      })
      .nth(1)
      .getByRole("button", { name: "Review this run" })
      .click();
    await expect(page.getByLabel("English translation")).toHaveValue(
      "Restores health.",
    );
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Translate", exact: true })
      .click();
    await page
      .getByRole("button", { name: "File workflow", exact: true })
      .click();
    await page.getByLabel("Translate Items.json", { exact: true }).check();
    await page
      .getByRole("button", { name: "Project guidance", exact: true })
      .click();
    await page
      .getByLabel("Project context text")
      .fill("# Game Characters\nノラ (Nora) - heroine\n");
    await page
      .getByRole("button", { name: "Game instructions", exact: true })
      .click();
    await page
      .getByLabel("Project context text")
      .fill("Use concise descriptions.");
    await page
      .getByRole("button", { name: "Save context", exact: true })
      .click();
    await expect(page.getByText("Saved to this project.")).toBeVisible();
    await page.getByRole("button", { name: /^Glossary/ }).click();
    await expect(page.getByLabel("Project context text")).toHaveValue(
      "# Game Characters\nノラ (Nora) - heroine\n",
    );
    await page
      .getByRole("button", { name: "Save context", exact: true })
      .click();
    await expect(page.getByText("Saved to this project.")).toBeVisible();
    await page
      .getByRole("button", { name: "File workflow", exact: true })
      .click();
    await expect(
      page.getByLabel("Translate Items.json", { exact: true }),
    ).toBeChecked();
    await page
      .getByRole("button", { name: "Preview file translation", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Start file translation", exact: true })
      .click();
    await expect(page.locator(".jobbar")).toContainText("Complete · 1/1 files");
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Review & test" })
      .click();
    await expect(page.getByText("0 of 2 entries reviewed")).toBeVisible();
    await page
      .locator(".review-list")
      .getByRole("button", { name: /体力を回復する/ })
      .click();
    await page.getByLabel("English translation").fill("Restores health.");
    await page
      .getByRole("button", { name: "Save & approve", exact: true })
      .click();
    await expect(page.getByText("1 of 2 entries reviewed")).toBeVisible();
    await page
      .locator(".review-list")
      .getByRole("button", { name: /^薬/ })
      .click();
    await page.getByLabel("English translation").fill("Potion");
    await page
      .getByRole("button", { name: "Save & approve", exact: true })
      .click();
    await expect(page.getByText("2 of 2 entries reviewed")).toBeVisible();
    await page.screenshot({
      path: path.join(evidence, "review.png"),
      fullPage: true,
    });
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Release", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Use reviewed files in project" })
      .click();
    await expect(
      page.getByText(
        "Reviewed files are now the source for subsequent runs in this workspace.",
      ),
    ).toBeVisible();
    const workspaces = path.join(temporary, "workspace", "projects");
    const projectFolder = path.join(workspaces, fs.readdirSync(workspaces)[0]);
    const working = JSON.parse(
      fs.readFileSync(
        path.join(projectFolder, "working", "Items.json"),
        "utf8",
      ),
    );
    expect(working[1].name).toBe("Potion");
    expect(working[1]._original.name).toBe("薬");
    expect(
      fs.readFileSync(
        path.join(projectFolder, "context", "glossary.txt"),
        "utf8",
      ),
    ).toContain("薬 (Potion)");
    expect(
      fs.readFileSync(path.join(source, "data", "Items.json"), "utf8"),
    ).toBe(original);
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Translate", exact: true })
      .click();
    await page.screenshot({
      path: path.join(evidence, "translation.png"),
      fullPage: true,
    });
    // Unapproved edits must recover, without changing the approved output or
    // run context. Close immediately after the final image edit to exercise
    // the real renderer-to-service shutdown barrier before its autosave timer.
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Review & test" })
      .click();
    await page
      .locator(".review-list")
      .getByRole("button", { name: /^薬/ })
      .click();
    await page
      .getByLabel("English translation")
      .fill("Unapproved potion draft");
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Translate", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Project guidance", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Game instructions", exact: true })
      .click();
    await page
      .getByLabel("Project context text")
      .fill("Unapplied instructions for a future run.");
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Images", exact: true })
      .click();
    await page
      .getByLabel("Translated image text", { exact: true })
      .fill("Continue adventure");
    await application.close();
    application = undefined;
    const persisted = JSON.parse(
      fs.readFileSync(path.join(projectFolder, "editor-drafts.json"), "utf8"),
    );
    expect(Object.values(persisted.review)).toContain(
      "Unapproved potion draft",
    );
    expect(persisted.context["skills/game.md"]).toBe(
      "Unapplied instructions for a future run.",
    );
    expect(
      fs.readFileSync(
        path.join(projectFolder, "context", "skills", "game.md"),
        "utf8",
      ),
    ).toBe("Use concise descriptions.");
    application = await electron.launch(launchOptions);
    const reopened = await application.firstWindow();
    reopened.on("pageerror", (error) => errors.push(error.message));
    await expect(reopened.getByText("Python service connected")).toBeVisible();
    await reopened
      .locator(".sidebar")
      .getByRole("button", { name: "Settings", exact: true })
      .click();
    await expect(
      reopened.getByLabel("Target language", { exact: true }),
    ).toHaveValue("Unsaved language draft");
    const reopenedSettings = await reopened.evaluate(() =>
      window.workspace.settingsGet(),
    );
    expect(reopenedSettings.values.language).toBe("English fixture");
    expect(reopenedSettings.engines.csv.SOURCE_COLUMN).toBe(2);
    expect(JSON.stringify(reopenedSettings)).not.toContain("ui-fixture-secret");

    await reopened
      .locator(".sidebar")
      .getByRole("button", { name: "Review & test" })
      .click();
    await reopened
      .locator(".review-list")
      .getByRole("button", { name: /^薬/ })
      .click();
    await expect(reopened.getByLabel("English translation")).toHaveValue(
      "Unapproved potion draft",
    );
    await reopened
      .locator(".sidebar")
      .getByRole("button", { name: "Release", exact: true })
      .click();
    await expect(
      reopened.getByRole("button", { name: "Use reviewed files in project" }),
    ).toBeDisabled();
    await reopened
      .locator(".sidebar")
      .getByRole("button", { name: "Translate", exact: true })
      .click();
    await reopened
      .getByRole("button", { name: "Project guidance", exact: true })
      .click();
    await reopened.getByRole("button", { name: /^Game instructions/ }).click();
    await expect(reopened.getByLabel("Project context text")).toHaveValue(
      "Unapplied instructions for a future run.",
    );
    await reopened
      .locator(".sidebar")
      .getByRole("button", { name: "Images", exact: true })
      .click();
    await expect(
      reopened.getByLabel("Translated image text", { exact: true }),
    ).toHaveValue("Continue adventure");
    await expect(
      reopened.getByRole("button", { name: "Approve preview", exact: true }),
    ).toBeDisabled();
    expect(fs.readFileSync(sourceImage)).toEqual(originalImage);
    expect(
      JSON.parse(
        fs.readFileSync(
          path.join(projectFolder, "working", "Items.json"),
          "utf8",
        ),
      )[1].name,
    ).toBe("Potion");
    // A conflicting on-disk draft must prevent silent close. Only the native
    // warning dialog is substituted, choosing the safe "Keep open" action.
    const draftsPath = path.join(projectFolder, "editor-drafts.json");
    const stableDrafts = JSON.parse(fs.readFileSync(draftsPath, "utf8"));
    fs.writeFileSync(
      draftsPath,
      JSON.stringify({ ...stableDrafts, revision: stableDrafts.revision + 1 }),
    );
    await reopened
      .locator(".sidebar")
      .getByRole("button", { name: "Review & test" })
      .click();
    await reopened
      .locator(".review-list")
      .getByRole("button", { name: /^薬/ })
      .click();
    await reopened
      .getByLabel("English translation")
      .fill("Draft retained after cancelled close");
    await application.evaluate(
      ({ dialog, BrowserWindow }) =>
        new Promise((resolve) => {
          dialog.showMessageBox = async () => {
            resolve(true);
            return { response: 0 };
          };
          BrowserWindow.getAllWindows()[0].close();
        }),
    );
    await expect(reopened.locator("body")).not.toHaveAttribute("inert", "");
    await expect(reopened.getByLabel("English translation")).toHaveValue(
      "Draft retained after cancelled close",
    );
    fs.writeFileSync(draftsPath, JSON.stringify(stableDrafts));
    await application.close();
    application = undefined;
    expect(
      Object.values(JSON.parse(fs.readFileSync(draftsPath, "utf8")).review),
    ).toContain("Draft retained after cancelled close");
    fs.writeFileSync(
      path.join(evidence, "electron-metrics.json"),
      JSON.stringify({ readyMs, navigationMs, metrics }, null, 2),
    );
    expect(errors).toEqual([]);
    console.log(
      JSON.stringify({
        readyMs: Math.round(readyMs),
        navigationMs: Math.round(navigationMs),
        electronWorkingSetMB: Math.round(
          metrics.reduce((sum, p) => sum + p.memory.workingSetSize, 0) / 1024,
        ),
      }),
    );
  } finally {
    if (application) await application.close();
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});
