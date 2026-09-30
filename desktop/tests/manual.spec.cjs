const { test, expect, _electron: electron } = require("@playwright/test");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
// Observe completion promptly without changing the expected state or timeout.
const complete = (locator) =>
  expect
    .poll(() => locator.textContent(), {
      intervals: [50, 100, 200],
      timeout: 10000,
    })
    .toBe("complete");

test("manual engines estimate locally and export isolated CSV output", async () => {
  const temporary = fs.mkdtempSync(
    path.join(os.tmpdir(), "dazedtl-manual-e2e-"),
  );
  const source = path.join(temporary, "Input files");
  fs.mkdirSync(source);
  const csv = "Source,Target\n薬,\n";
  const database = JSON.stringify([
    null,
    { id: 1, name: "薬", description: "回復する。", note: "Keep this note" },
  ]);
  fs.writeFileSync(path.join(source, "items.csv"), csv);
  fs.writeFileSync(path.join(source, "Items.json"), database);
  const env = {
    ...process.env,
    DAZEDTL_DESKTOP_WORKSPACE: path.join(temporary, "workspace"),
    DAZEDTL_DESKTOP_PROFILE: path.join(temporary, "profile"),
    DAZEDTL_DESKTOP_ALLOW_LIVE: "0",
    DAZEDTL_DESKTOP_PROVIDERS: "0",
    DAZEDTL_TEST_OFFLINE: "1",
  };
  delete env.ELECTRON_RUN_AS_NODE;
  const launchOptions = {
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
    application = await electron.launch(launchOptions);
    let page = await application.firstWindow();
    page.on("pageerror", (error) => errors.push(error.message));
    await expect(page.getByText("Python service connected")).toBeVisible();
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Manual engines", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Use any supported engine." }),
    ).toBeVisible();
    const registered = await page.evaluate(() =>
      window.workspace.manualState(),
    );
    await expect(
      page.getByLabel("Manual translation engine").locator("option"),
    ).toHaveCount(registered.engines.length);
    await page.getByLabel("Manual translation engine").selectOption("CSV");
    await page.getByLabel("Manual input folder", { exact: true }).fill(source);
    await page
      .getByRole("button", { name: "Read input files", exact: true })
      .click();
    await expect(
      page.getByLabel("Translate items.csv", { exact: true }),
    ).toBeChecked();
    await page
      .getByLabel("Manual run mode", { exact: true })
      .selectOption("offline");
    await page
      .getByRole("button", { name: "Run offline engine check", exact: true })
      .click();
    await complete(page.locator(".manual-status"));
    await page
      .getByRole("button", { name: "Export translated files", exact: true })
      .click();
    await expect(page.locator(".manual-export .output-path")).toBeVisible();
    const output = await page
      .locator(".manual-export .output-path")
      .innerText();
    const translated = fs.readFileSync(path.join(output, "items.csv"), "utf8");
    expect(translated).toContain("Offline test text");
    expect(translated).toContain("薬");
    expect(fs.readFileSync(path.join(source, "items.csv"), "utf8")).toBe(csv);
    await page
      .getByLabel("Manual translation engine")
      .selectOption("RPG Maker MV/MZ");
    await page
      .getByRole("button", { name: "Read input files", exact: true })
      .click();
    await page
      .getByLabel("Manual run mode", { exact: true })
      .selectOption("estimate");
    await page
      .getByRole("button", { name: "Estimate selected files", exact: true })
      .click();
    await complete(page.locator(".manual-status"));
    await expect(
      page.getByText("Live estimate", { exact: true }),
    ).toBeVisible();
    const manual = await page.evaluate(() => window.workspace.manualState());
    expect(manual.jobs[0].estimate.input_tokens).toBeGreaterThan(0);
    expect(manual.jobs[0].outputs).toEqual({});
    expect(fs.readFileSync(path.join(source, "Items.json"), "utf8")).toBe(
      database,
    );
    const state = await page.evaluate(() => window.workspace.state());
    expect(state.budget.requests).toBe(0);
    const evidence = path.resolve(__dirname, "../../.tmp-ui/desktop-evidence");
    fs.mkdirSync(evidence, { recursive: true });
    await page.screenshot({
      path: path.join(evidence, "manual-engines.png"),
      fullPage: true,
    });
    // Restart/export ownership is covered directly by the persisted-job
    // component test; this smoke keeps the real engine and UI export path.
    expect(
      (await page.evaluate(() => window.workspace.manualState())).jobs,
    ).toHaveLength(2);
    const legacy = path.join(temporary, "Legacy batch run");
    fs.mkdirSync(path.join(legacy, "log"), { recursive: true });
    fs.writeFileSync(
      path.join(legacy, "log/batch_history.json"),
      JSON.stringify({
        batches: [
          {
            id: "saved-provider-job",
            status: "fetched",
            provider: "openai",
            model: "gpt-4.1",
            key_name: "Original account",
            request_count: 1,
            file_set: ["items.csv"],
            actual_cost: 0.001,
          },
        ],
      }),
    );
    fs.writeFileSync(
      path.join(legacy, "log/batch_state.json"),
      JSON.stringify({
        status: "queued",
        run_id: "unsubmitted-legacy",
        provider: "openai",
        model: "gpt-4.1",
        key_name: "Original account",
        file_set: ["items.csv"],
      }),
    );
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Batch history", exact: true })
      .click();
    await page.getByLabel("Legacy run folder", { exact: true }).fill(legacy);
    await page
      .getByRole("button", { name: "Add legacy run folder", exact: true })
      .click();
    await expect(
      page.getByRole("button", {
        name: "local-queue:unsubmitted-legacy",
        exact: true,
      }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "saved-provider-job", exact: true })
      .click();
    await expect(
      page.getByRole("button", {
        name: "Refresh provider status",
        exact: true,
      }),
    ).toBeDisabled();
    await expect(
      page.getByText("Saved credential: Original account", { exact: false }),
    ).toBeVisible();
    await page.screenshot({
      path: path.join(evidence, "batch-history.png"),
      fullPage: true,
    });
    expect(errors).toEqual([]);
  } finally {
    if (application) await application.close();
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});
