const { test, expect, _electron: electron } = require("@playwright/test");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
// Poll local fixture state promptly; keep every assertion and timeout intact.
const poll = (read, timeout) =>
  expect.poll(read, { intervals: [50, 100, 200], timeout });

test("guided phases retain originals, reject stale export approval and recover guidance drafts", async () => {
  const temporary = fs.mkdtempSync(
    path.join(os.tmpdir(), "dazedtl-guided-e2e-"),
  );
  const source = path.join(temporary, "Game 日本語");
  fs.mkdirSync(path.join(source, "data"), { recursive: true });
  fs.mkdirSync(path.join(source, "js"));
  fs.writeFileSync(path.join(source, "data/System.json"), "{}");
  fs.writeFileSync(path.join(source, "js/plugins.js"), "var $plugins = [];");
  const original = JSON.stringify([
    null,
    { id: 1, name: "薬", description: "回復する。", note: "" },
  ]);
  const itemPath = path.join(source, "data/Items.json");
  fs.writeFileSync(itemPath, original);
  const env = {
    ...process.env,
    DAZEDTL_DESKTOP_WORKSPACE: path.join(temporary, "workspace"),
    DAZEDTL_DESKTOP_PROFILE: path.join(temporary, "profile"),
    DAZEDTL_DESKTOP_ALLOW_LIVE: "0",
    DAZEDTL_DESKTOP_PROVIDERS: "0",
    DAZEDTL_TEST_OFFLINE: "1",
  };
  delete env.ELECTRON_RUN_AS_NODE;
  const options = {
    executablePath:
      process.env.DAZEDTL_PACKAGED_APP ||
      process.env.DAZEDTL_ELECTRON ||
      undefined,
    args: process.env.DAZEDTL_PACKAGED_APP
      ? []
      : [path.resolve(__dirname, "..")],
    env,
  };
  let application;
  const errors = [];
  try {
    application = await electron.launch(options);
    let page = await application.firstWindow();
    page.on("pageerror", (error) => errors.push(error.message));
    await expect(page.getByText("Python service connected")).toBeVisible();
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Guided workflow", exact: true })
      .click();
    await page.getByLabel("Guided game root").fill(source);
    await page
      .getByRole("button", { name: "Detect game", exact: true })
      .click();
    await page.getByLabel("System.json", { exact: true }).uncheck();
    await page
      .getByRole("button", { name: "Import 1 selected files", exact: true })
      .click();
    await expect(
      page.getByRole("dialog", { name: "Confirm guided action" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Cancel", exact: true }),
    ).toBeFocused();
    // Confirmation owns keyboard focus; Escape cancels without importing.
    await page.keyboard.press("Shift+Tab");
    await expect(
      page.getByRole("button", { name: "Run action", exact: true }),
    ).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(
      page.getByRole("dialog", { name: "Confirm guided action" }),
    ).toBeHidden();
    expect(
      (await page.evaluate(() => window.workspace.workflowState())).project
        .imported,
    ).toEqual([]);
    await expect(
      page.getByRole("button", {
        name: "Import 1 selected files",
        exact: true,
      }),
    ).toBeFocused();
    await page
      .getByRole("button", { name: "Import 1 selected files", exact: true })
      .click();
    await page.getByRole("button", { name: "Run action", exact: true }).click();
    await expect(
      page.getByText("1 files currently imported", { exact: true }),
    ).toBeVisible();
    await page
      .getByRole("navigation", { name: "Guided stages" })
      .getByRole("button", { name: /Translation phase 1/ })
      .click();
    await page.getByLabel("Workflow translation mode").selectOption("offline");
    await page
      .getByRole("button", { name: "Translate database", exact: true })
      .click();
    await poll(
      () => page.locator(".workflow-run .badge").textContent(),
      10000,
    ).toBe("complete");
    await poll(
      async () =>
        (await page.evaluate(() => window.workspace.workflowState())).project
          .collected.length,
    ).toBe(1);
    expect(fs.readFileSync(itemPath, "utf8")).toBe(original);
    await page
      .getByRole("navigation", { name: "Guided stages" })
      .getByRole("button", { name: /Export/ })
      .click();
    await page
      .getByRole("button", { name: "Export selected files", exact: true })
      .click();
    fs.writeFileSync(itemPath, original + "\n");
    await page.getByRole("button", { name: "Run action", exact: true }).click();
    await expect(
      page
        .getByRole("dialog", { name: "Confirm guided action" })
        .getByRole("alert"),
    ).toContainText(/changed after this preview/);
    await expect(
      page.getByRole("button", { name: "Run action", exact: true }),
    ).toBeDisabled();
    expect(fs.readFileSync(itemPath, "utf8")).toBe(original + "\n");
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    fs.writeFileSync(itemPath, original);
    await page
      .getByRole("button", { name: "Export selected files", exact: true })
      .click();
    await page.getByRole("button", { name: "Run action", exact: true }).click();
    await poll(() => fs.readFileSync(itemPath, "utf8")).toContain(
      "Offline test text",
    );
    const translated = JSON.parse(fs.readFileSync(itemPath, "utf8"));
    expect(translated[1]._original.name).toBe("薬");
    await poll(
      async () =>
        (await page.evaluate(() => window.workspace.workflowState())).active,
    ).toBeNull();
    await page
      .getByRole("navigation", { name: "Guided stages" })
      .getByRole("button", { name: /Setup/ })
      .click();
    await page
      .getByLabel("Translation quirks", { exact: true })
      .fill("Preserve the heroine's dry humor.");
    const evidence = path.resolve(__dirname, "../../.tmp-ui/desktop-evidence");
    fs.mkdirSync(evidence, { recursive: true });
    await page.screenshot({
      path: path.join(evidence, "guided-workflow.png"),
      fullPage: true,
    });
    expect(
      (await page.evaluate(() => window.workspace.state())).budget.requests,
    ).toBe(0);
    await application.close();
    application = await electron.launch(options);
    page = await application.firstWindow();
    page.on("pageerror", (error) => errors.push(error.message));
    await expect(page.getByText("Python service connected")).toBeVisible();
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Guided workflow", exact: true })
      .click();
    await expect(
      page.getByLabel("Translation quirks", { exact: true }),
    ).toHaveValue("Preserve the heroine's dry humor.");
    expect(fs.existsSync(path.join(source, ".dazedtl/skills/quirks.md"))).toBe(
      false,
    );
    expect(errors).toEqual([]);
  } finally {
    if (application) await application.close();
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});
