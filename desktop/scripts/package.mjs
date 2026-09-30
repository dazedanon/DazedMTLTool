import { packager } from "@electron/packager";
import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import packageFormat from "../electron/package-format.cjs";

const desktop = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const repository = path.dirname(desktop);
const output = path.join(desktop, "out");
await fs.rm(path.join(output, "package-result.json"), { force: true });
const stage = path.join(output, "stage");
const python =
  process.env.DAZEDTL_BUILD_PYTHON ||
  path.join(
    repository,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
const offline = process.argv.slice(2).includes("--offline");
if (process.argv.slice(2).some((value) => value !== "--offline"))
  throw new Error("Supported package option: --offline");
function run(command, args, cwd = desktop) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      stdio: "inherit",
      windowsHide: true,
    });
    child.on("error", reject);
    child.on("exit", (code) =>
      code === 0
        ? resolve()
        : reject(new Error(`Build step exited with ${code}`)),
    );
  });
}
await run(process.execPath, [
  path.join(desktop, "node_modules/typescript/bin/tsc"),
  "--noEmit",
]);
await run(process.execPath, [
  path.join(desktop, "node_modules/vite/bin/vite.js"),
  "build",
]);
await run(
  python,
  [
    path.join(repository, "scripts/build_desktop.py"),
    ...(offline ? ["--offline"] : []),
  ],
  repository,
);
const appStage = path.join(output, "app-stage");
await fs.rm(appStage, { recursive: true, force: true });
await fs.mkdir(appStage, { recursive: true });
await fs.cp(path.join(desktop, "electron"), path.join(appStage, "electron"), {
  recursive: true,
});
await fs.cp(path.join(desktop, "dist"), path.join(appStage, "dist"), {
  recursive: true,
});
const project = JSON.parse(
  await fs.readFile(path.join(desktop, "package.json"), "utf8"),
);
await fs.writeFile(
  path.join(appStage, "package.json"),
  JSON.stringify(
    {
      name: "dazedtl",
      productName: "DazedTL",
      version: project.version,
      main: "electron/main.cjs",
      private: true,
    },
    null,
    2,
  ),
);
await fs.copyFile(
  path.join(repository, "LICENSE.md"),
  path.join(appStage, "LICENSE.md"),
);
let notices = "DazedTL renderer third-party notices\n\n";
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
  const files = (await fs.readdir(folder)).filter((file) =>
    /^(LICENSE|COPYING)(\.|$)/i.test(file),
  );
  if (!files.length) throw new Error(`Missing license for ${name}`);
  notices += `\n${name} ${pkg.version}\n${"=".repeat(60)}\n`;
  for (const file of files)
    notices += (await fs.readFile(path.join(folder, file), "utf8")) + "\n";
}
await fs.writeFile(path.join(stage, "THIRD-PARTY-NOTICES.txt"), notices);
const electron = JSON.parse(
  await fs.readFile(
    path.join(desktop, "node_modules/electron/package.json"),
    "utf8",
  ),
);
const zipName = `electron-v${electron.version}-${process.platform}-${process.arch}.zip`;
let zipDir = process.env.ELECTRON_ZIP_DIR;
if (!zipDir && process.platform === "linux") {
  const cache = path.join(os.homedir(), ".cache/electron");
  for (const folder of await fs.readdir(cache).catch(() => [])) {
    const candidate = path.join(cache, folder);
    if (
      await fs
        .stat(path.join(candidate, zipName))
        .then((stat) => stat.isFile())
        .catch(() => false)
    ) {
      zipDir = candidate;
      break;
    }
  }
}
if (offline && !zipDir)
  throw new Error(
    "Set ELECTRON_ZIP_DIR to a cached Electron ZIP directory for offline packaging.",
  );
const packages = await packager({
  dir: appStage,
  out: path.join(output, "packages"),
  name: "DazedTL",
  executableName: "dazedtl",
  appVersion: project.version,
  appBundleId: "dev.dazedtl.desktop",
  platform: process.platform,
  arch: process.arch,
  electronVersion: electron.version,
  ...(zipDir ? { electronZipDir: zipDir } : {}),
  asar: true,
  prune: false,
  overwrite: true,
  extraResource: [
    path.join(stage, "backend"),
    path.join(stage, "runtime.json"),
    path.join(stage, "THIRD-PARTY-NOTICES.txt"),
  ],
  ...(process.platform === "win32"
    ? { icon: path.join(repository, "assets/icon.ico") }
    : {}),
});
// Packager's extra-resource copier rewrites relative links to the build tree.
// Preserve Python's internal links so extracted/moved releases are standalone.
for (const target of packages) {
  const resources = path.join(
    target,
    process.platform === "darwin"
      ? "DazedTL.app/Contents/Resources"
      : "resources",
  );
  await fs.cp(path.join(stage, "python"), path.join(resources, "python"), {
    recursive: true,
    dereference: false,
    verbatimSymlinks: true,
  });
}
const result = {
  packages,
  executable: path.join(
    packages[0],
    process.platform === "darwin"
      ? "DazedTL.app/Contents/MacOS/dazedtl"
      : process.platform === "win32"
        ? "dazedtl.exe"
        : "dazedtl",
  ),
  python: "3.12.14",
  signed: false,
  published: false,
};
const manifest = await packageFormat.createManifest(packages[0], {
  version: project.version,
  platform: process.platform,
  arch: process.arch,
  executable: path
    .relative(packages[0], result.executable)
    .split(path.sep)
    .join("/"),
  signed: false,
});
const archive = path.join(
  output,
  `dazedtl-desktop-${process.platform}-${process.arch}.tar.gz`,
);
await run(python, [
  path.join(desktop, "backend/package_archive.py"),
  "create",
  packages[0],
  archive,
]);
result.packageId = manifest.id;
result.archive = archive;
result.sha256 = await packageFormat.fileHash(archive);
await fs.writeFile(
  path.join(output, "package-result.json"),
  JSON.stringify(result, null, 2),
);
console.log(JSON.stringify(result));
