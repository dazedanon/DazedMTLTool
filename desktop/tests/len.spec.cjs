const { test, expect, _electron: electron } = require("@playwright/test");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
// Poll local fixture state promptly; keep every assertion and timeout intact.
const poll = (read) => expect.poll(read, { intervals: [50, 100, 200] });

test("Len handoff recovers scope and guidance drafts without altering source files", async () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-len-e2e-"));
  const source = path.join(temporary, "Game 日本語");
  fs.mkdirSync(source);
  fs.writeFileSync(path.join(source, "Game.dat"), "unchanged source");
  fs.writeFileSync(path.join(source, "game.txt"), "Japanese v1\n");
  const official = path.join(temporary, "Official v2");
  fs.mkdirSync(official);
  fs.writeFileSync(path.join(official, "Game.dat"), "unchanged source");
  fs.writeFileSync(path.join(official, "game.txt"), "Japanese v2\n");
  const env = {
    ...process.env,
    DAZEDTL_DESKTOP_WORKSPACE: path.join(temporary, "workspace"),
    DAZEDTL_DESKTOP_PROFILE: path.join(temporary, "profile"),
    DAZEDTL_DESKTOP_ALLOW_LIVE: "0",
    DAZEDTL_DESKTOP_PROVIDERS: "0",
    DAZEDTL_TEST_OFFLINE: "1",
    GIT_CONFIG_GLOBAL: os.devNull,
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_ATTR_NOSYSTEM: "1",
  };
  delete env.ELECTRON_RUN_AS_NODE;
  let application;
  const errors = [];
  async function launch() {
    application = await electron.launch({
      executablePath:
        process.env.DAZEDTL_PACKAGED_APP ||
        process.env.DAZEDTL_ELECTRON ||
        undefined,
      args: process.env.DAZEDTL_PACKAGED_APP
        ? []
        : [path.resolve(__dirname, "..")],
      env,
    });
    const page = await application.firstWindow();
    page.on("pageerror", (e) => errors.push(e.message));
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Len’s Method", exact: true })
      .click();
    return page;
  }
  try {
    let page = await launch();
    await page.getByLabel("Len game folder").fill(source);
    await page
      .getByRole("main")
      .getByRole("button", { name: "Open game", exact: true })
      .click();
    await page
      .getByLabel("Len project instructions")
      .fill("Preserve character voices.");
    await page
      .getByRole("button", { name: "Review shared guidance", exact: true })
      .click();
    await page
      .getByLabel("Len guidance text")
      .fill("# Game Characters\n名前 (Name)\n");
    expect(fs.existsSync(path.join(source, ".dazedtl/glossary.txt"))).toBe(
      false,
    );
    await application.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].close(),
    );
    await application.close();
    application = null;
    page = await launch();
    await expect(page.getByLabel("Len project instructions")).toHaveValue(
      "Preserve character voices.",
    );
    await page
      .getByRole("button", { name: "Review shared guidance", exact: true })
      .click();
    await expect(page.getByLabel("Len guidance text")).toHaveValue(
      "# Game Characters\n名前 (Name)\n",
    );
    await page
      .getByRole("button", { name: "Save guidance to game", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Prepare & copy handoff", exact: true })
      .click();
    await poll(
      async () =>
        (await page.evaluate(() => window.workspace.lenState())).jobs[0]
          ?.status,
    ).toBe("complete");
    await page
      .getByRole("button", { name: "Refresh progress", exact: true })
      .click();
    await poll(() =>
      application.evaluate(({ clipboard }) => clipboard.readText()),
    ).toContain("Preserve character voices.");
    const clipboard = await application.evaluate(({ clipboard }) =>
      clipboard.readText(),
    );
    expect(clipboard).toContain("Preserve character voices.");
    expect(clipboard).toContain(env.DAZEDTL_DESKTOP_WORKSPACE);
    expect(clipboard).toContain("DAZEDTL_DESKTOP_WORKSPACE");
    expect(fs.readFileSync(path.join(source, "Game.dat"), "utf8")).toBe(
      "unchanged source",
    );
    expect(
      JSON.parse(
        fs.readFileSync(path.join(source, ".dazedtl/len-method/project.json")),
      ).mode,
    ).toBe("local");
    expect(
      (await page.evaluate(() => window.workspace.state())).budget.requests,
    ).toBe(0);
    const evidence = path.resolve(__dirname, "../../.tmp-ui/desktop-evidence");
    fs.mkdirSync(evidence, { recursive: true });
    await page.screenshot({
      path: path.join(evidence, "len-workflow.png"),
      fullPage: true,
    });
    // The Len navigation preserves the selected game and native-file policy.
    await page
      .locator(".len-workspace")
      .getByRole("button", { name: "Git version updates", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Git version updates", exact: true }),
    ).toBeVisible();
    await poll(
      async () =>
        (await page.evaluate(() => window.workspace.versionState())).active,
    ).toBeNull();
    await expect(
      page.getByLabel("Preserve native game bytes and local Len work"),
    ).toBeChecked();
    await page.getByLabel(/The selected game is still untranslated/).check();
    await page.getByLabel("Current game version", { exact: true }).fill("1.00");
    async function gitAction(label, confirm, expected = "complete") {
      await page.getByRole("button", { name: label, exact: true }).click();
      if (confirm)
        await page
          .getByRole("button", { name: "Confirm Git action", exact: true })
          .click();
      await poll(
        async () =>
          (await page.evaluate(() => window.workspace.versionState())).jobs[0]
            ?.status,
      ).toBe(expected);
    }
    await gitAction("Create version baselines", true);
    await page
      .getByLabel("New official game or patch folder", { exact: true })
      .fill(official);
    await page.getByLabel("New official version", { exact: true }).fill("1.01");
    await gitAction("Preview official update", false);
    await expect(
      page.getByRole("heading", { name: "Review version 1.01", exact: true }),
    ).toBeVisible();
    fs.writeFileSync(
      path.join(official, "game.txt"),
      "Japanese v2 changed after preview\n",
    );
    await gitAction("Apply reviewed update", true, "failed");
    expect(fs.readFileSync(path.join(source, "game.txt"), "utf8")).toBe(
      "Japanese v1\n",
    );
    await gitAction("Preview official update", false);
    await gitAction("Apply reviewed update", true);
    expect(fs.readFileSync(path.join(source, "game.txt"), "utf8")).toBe(
      "Japanese v2 changed after preview\n",
    );
    await gitAction("Copy post-update handoff", false);
    await poll(() =>
      application.evaluate(({ clipboard }) => clipboard.readText()),
    ).toContain("version `1.01`");
    const version = await page.evaluate(() => window.workspace.versionState());
    expect(version.status.current_branch).toBe(
      version.status.translation_branch,
    );
    expect(version.status.applied_update_version).toBe("1.01");
    expect(version.status.worktree_clean).toBe(true);
    await page.screenshot({
      path: path.join(evidence, "git-version-workflow.png"),
      fullPage: true,
    });
    // Continue the same any-engine game into images. The generated portable
    // job stands in for work previously reviewed in the Qt editor.
    const pixels = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAKAAAAA8CAYAAADha7EVAAAAt0lEQVR4nO3UMREAIAADMUAJAyP+7YGMXxIDXf4697lvQGRVwyBAch6QlABJCZCUAEkJkJQASQmQlABJCZCUAEkJkJQASQmQlABJCZCUAEkJkJQASQmQlABJCZCUAEkJkJQASQmQlABJCZCUAEkJkJQASQmQlABJCZCUAEkJkJQASQmQlABJCZCUAEkJkJQASQmQlABJCZCUAEkJkJQASQmQlABJCZCUAEkJkJQASQmQlABJCZBR+jYdAeflBq+NAAAAAElFTkSuQmCC",
      "base64",
    );
    fs.writeFileSync(path.join(source, "menu.png"), pixels);
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Images", exact: true })
      .click();
    await page.getByLabel("Image game folder", { exact: true }).fill(source);
    async function imageAction(label, confirm = false) {
      await page.getByRole("button", { name: label, exact: true }).click();
      if (confirm)
        await page
          .getByRole("button", { name: "Confirm image action", exact: true })
          .click();
      await poll(
        async () =>
          (await page.evaluate(() => window.workspace.assetState())).jobs[0]
            ?.status,
      ).toBe("complete");
    }
    await imageAction("Open game images");
    await expect(page.getByLabel("Select image menu.png")).toBeVisible();
    await imageAction("Make all editable");
    const portableRoot = path.join(source, ".dazedtl/images");
    fs.mkdirSync(path.join(portableRoot, ".dazedtl"), { recursive: true });
    fs.writeFileSync(
      path.join(portableRoot, ".dazedtl/image_job.json"),
      JSON.stringify({
        format: "dazedtl-image-job",
        version: 4,
        root: portableRoot,
        images: [
          {
            image: "menu.png",
            index: 0,
            width: 160,
            height: 60,
            status: "confirmed",
            blocks: [
              {
                id: "title",
                box: [20, 12, 120, 32],
                source: "開始",
                target: "Play",
                style: {
                  background: "solid",
                  fill: [32, 36, 44, 255],
                  text_color: [255, 255, 255, 255],
                  cap_height: 15,
                  locked: true,
                },
              },
            ],
          },
        ],
      }),
    );
    await imageAction("Edit image text");
    await expect(page.getByLabel("Translated image text")).toHaveValue("Play");
    await page.getByLabel("Translated image text").fill("Start game");
    await page
      .getByRole("button", { name: "Render preview", exact: true })
      .click();
    await expect(
      page.getByRole("button", {
        name: "Approve and write editable image",
        exact: true,
      }),
    ).toBeEnabled();
    await page
      .getByRole("button", {
        name: "Approve and write editable image",
        exact: true,
      })
      .click();
    await expect(
      page.getByRole("button", {
        name: "Written to editable image",
        exact: true,
      }),
    ).toBeVisible();
    expect(fs.readFileSync(path.join(source, "menu.png"))).toEqual(pixels);
    expect(fs.readFileSync(path.join(portableRoot, "menu.png"))).not.toEqual(
      pixels,
    );
    await page.screenshot({
      path: path.join(evidence, "portable-image-editor.png"),
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "Game image gallery", exact: true })
      .click();
    await imageAction("Prepare for game", true);
    expect(fs.readFileSync(path.join(source, "menu.png"))).toEqual(
      fs.readFileSync(path.join(portableRoot, "menu.png")),
    );
    expect(
      JSON.parse(
        fs.readFileSync(path.join(portableRoot, ".dazedtl/image_job.json")),
      ).images[0].blocks[0].target,
    ).toBe("Start game");
    expect(
      (await page.evaluate(() => window.workspace.state())).budget.requests,
    ).toBe(0);
    await page.screenshot({
      path: path.join(evidence, "image-gallery.png"),
      fullPage: true,
    });
    expect(errors).toEqual([]);
  } finally {
    if (application) await application.close();
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});
