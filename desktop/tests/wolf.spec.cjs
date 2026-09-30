const { test, expect, _electron: electron } = require("@playwright/test");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
// Poll local fixture state promptly; keep every assertion and timeout intact.
const poll = (read, timeout) =>
  expect.poll(read, { intervals: [50, 100, 200], timeout });

test("WOLF extraction, offline phase and repeat injection retain pristine event text", async () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-wolf-e2e-"));
  const source = path.join(temporary, "WOLF 日本語");
  fs.mkdirSync(path.join(source, "Data/BasicData"), { recursive: true });
  fs.mkdirSync(path.join(source, "Data/Evtext"));
  fs.writeFileSync(path.join(source, "Data/BasicData/CommonEvent.dat"), "");
  // Japanese "good morning" encoded as Shift-JIS; generated event-text fixture.
  const original = Buffer.from(
    "82a882cd82e682a482b282b482a282dc82b781420a",
    "hex",
  );
  const input = path.join(source, "Data/Evtext/001.txt");
  fs.writeFileSync(input, original);
  const env = {
    ...process.env,
    DAZEDTL_DESKTOP_WORKSPACE: path.join(temporary, "workspace"),
    DAZEDTL_DESKTOP_PROFILE: path.join(temporary, "profile"),
    DAZEDTL_DESKTOP_ALLOW_LIVE: "0",
    DAZEDTL_DESKTOP_PROVIDERS: "0",
    DAZEDTL_TEST_OFFLINE: "1",
  };
  delete env.ELECTRON_RUN_AS_NODE;
  let application;
  const errors = [];
  try {
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
    await expect(
      page.getByRole("heading", { name: "WOLF RPG", exact: true }),
    ).toBeVisible();
    async function run(label) {
      await page.getByRole("button", { name: label, exact: true }).click();
      await page
        .getByRole("button", { name: "Run action", exact: true })
        .click();
      await poll(
        async () =>
          (await page.evaluate(() => window.workspace.workflowState())).active,
      ).toBeNull();
      const state = await page.evaluate(() => window.workspace.workflowState());
      expect(state.jobs[0].status, state.jobs[0].message).toBe("complete");
    }
    await run("Extract text and backups");
    await run("Import 1 selected files");
    await page
      .getByRole("navigation", { name: "Guided stages" })
      .getByRole("button", { name: /Maps & events/ })
      .click();
    await page.getByLabel("Workflow translation mode").selectOption("offline");
    await page
      .getByRole("button", { name: "Translate maps and events", exact: true })
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
    expect(fs.readFileSync(input)).toEqual(original);
    await page
      .getByRole("navigation", { name: "Guided stages" })
      .getByRole("button", { name: /Check/ })
      .click();
    await run("Run name and injection checks");
    await page
      .getByRole("navigation", { name: "Guided stages" })
      .getByRole("button", { name: /Apply/ })
      .click();
    await run("Apply all translations");
    expect(fs.readFileSync(input, "utf8")).toContain("Offline test text");
    const backup = path.join(source, "wolf_json/originals/Evtext/001.txt");
    expect(fs.readFileSync(backup)).toEqual(original);
    await run("Apply all translations");
    expect(fs.readFileSync(backup)).toEqual(original);
    const evidence = path.resolve(__dirname, "../../.tmp-ui/desktop-evidence");
    fs.mkdirSync(evidence, { recursive: true });
    await page.screenshot({
      path: path.join(evidence, "wolf-workflow.png"),
      fullPage: true,
    });
    const state = await page.evaluate(() => window.workspace.state());
    expect(state.budget.requests).toBe(0);
    expect(errors).toEqual([]);
  } finally {
    if (application) await application.close();
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});
