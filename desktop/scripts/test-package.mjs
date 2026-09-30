import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const desktop = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const result = JSON.parse(
  fs.readFileSync(path.join(desktop, "out/package-result.json"), "utf8"),
);
if (!fs.existsSync(result.executable))
  throw new Error("Build the package before running its UI test.");
const child = spawn(
  process.execPath,
  [path.join(desktop, "node_modules/@playwright/test/cli.js"), "test"],
  {
    cwd: desktop,
    stdio: "inherit",
    env: { ...process.env, DAZEDTL_PACKAGED_APP: result.executable },
  },
);
child.on("error", (error) => {
  console.error(error.message);
  process.exitCode = 1;
});
child.on("exit", (code) => {
  process.exitCode = code ?? 1;
});
