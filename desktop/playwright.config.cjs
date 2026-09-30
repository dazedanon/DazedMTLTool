const { defineConfig } = require("@playwright/test");
module.exports = defineConfig({
  testDir: "./tests",
  timeout: 20000,
  globalTimeout: 60000,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: { trace: "retain-on-failure" },
});
