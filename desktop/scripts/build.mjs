import fs from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const desktop = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const root = path.dirname(desktop);
const hash = (data) => createHash("sha256").update(data).digest("hex");
for (const args of [
  ["node_modules/typescript/bin/tsc", "--noEmit"],
  ["node_modules/vite/bin/vite.js", "build"],
]) {
  const result = spawnSync(process.execPath, args, {
    cwd: desktop,
    stdio: "inherit",
  });
  if (result.status !== 0) process.exit(result.status || 1);
}
async function files(folder, base = folder) {
  const result = {};
  for (const entry of await fs.readdir(folder, { withFileTypes: true })) {
    const file = path.join(folder, entry.name);
    if (entry.isDirectory()) Object.assign(result, await files(file, base));
    else if (entry.isFile())
      result[path.relative(base, file).split(path.sep).join("/")] = hash(
        await fs.readFile(file),
      );
    else throw new Error("Build inputs must be regular files.");
  }
  return result;
}
let notices = "DazedTL renderer third-party notices\n";
for (const name of [
  "react",
  "react-dom",
  "scheduler",
  "lucide-react",
  "vite",
]) {
  const folder = path.join(desktop, "node_modules", name);
  const pkg = JSON.parse(
    await fs.readFile(path.join(folder, "package.json"), "utf8"),
  );
  const licenses = (await fs.readdir(folder)).filter((file) =>
    /^(LICENSE|COPYING)(\.|$)/i.test(file),
  );
  if (!licenses.length) throw new Error(`Missing license for ${name}`);
  notices += `\n${name} ${pkg.version}\n`;
  for (const license of licenses)
    notices += await fs.readFile(path.join(folder, license), "utf8");
}
await fs.writeFile(path.join(desktop, "dist/THIRD-PARTY-NOTICES.txt"), notices);
const inputs = {};
for (const [name, digest] of Object.entries(
  await files(path.join(desktop, "src")),
))
  inputs["src/" + name] = digest;
for (const name of [
  "index.html",
  "vite.config.ts",
  "tsconfig.json",
  "package.json",
  "package-lock.json",
]) {
  inputs[name] = hash(await fs.readFile(path.join(desktop, name)));
}
const output = await files(path.join(desktop, "dist"));
await fs.writeFile(
  path.join(desktop, "dist/renderer-manifest.json"),
  JSON.stringify({ version: 1, inputs, files: output }, null, 2) + "\n",
);

// The legacy Qt updater overwrites engine .py files without backing up their
// embedded user settings. Git archives omit these four originals; the launcher
// migrates their options before installing these matching, versioned defaults.
const defaults = path.join(desktop, "engine-defaults");
await fs.mkdir(defaults, { recursive: true });
const engines = {};
for (const name of ["rpgmakermvmz.py", "csv.py", "wolf.py", "srpg.py"]) {
  const data = await fs.readFile(path.join(root, "modules", name));
  await fs.writeFile(path.join(defaults, name), data);
  engines[name] = hash(data);
}
const shared = {};
for (const name of await fs.readdir(path.join(root, "data/skills"))) {
  if (name.endsWith(".md"))
    shared["skills/" + name] = hash(
      await fs.readFile(path.join(root, "data/skills", name)),
    );
}
for (const name of ["translation_contexts.json", "glossary_base.txt"])
  shared[name] = hash(await fs.readFile(path.join(root, "data", name)));
await fs.writeFile(
  path.join(defaults, "manifest.json"),
  JSON.stringify({ version: 1, files: engines, shared_data: shared }, null, 2) +
    "\n",
);
