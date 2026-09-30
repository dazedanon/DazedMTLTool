// Shared by the builder and updater. A manifest checks integrity, not authorship.
// Electron's patched fs exposes app.asar as a virtual directory. Package
// integrity and copying must use the bytes that are actually on disk.
const nativeFs = process.versions.electron
  ? require("original-fs")
  : require("node:fs");
const fs = nativeFs.promises;
const path = require("node:path");
const { createHash } = require("node:crypto");
const { createReadStream } = nativeFs;
const MANIFEST = "desktop-package.json";
const hash = (value) => createHash("sha256").update(value).digest("hex");
async function fileHash(file) {
  const digest = createHash("sha256");
  for await (const chunk of createReadStream(file)) digest.update(chunk);
  return digest.digest("hex");
}
function inside(root, value) {
  if (
    typeof value !== "string" ||
    /[\\:\0]/.test(value) ||
    value.split("/").some((s) => !s || s === "." || s === "..")
  )
    throw new Error("Invalid application package path.");
  const target = path.resolve(root, value);
  if (!target.startsWith(path.resolve(root) + path.sep))
    throw new Error("Package path escaped its folder.");
  return target;
}
async function inventory(root) {
  const files = {};
  async function walk(folder, prefix = "") {
    for (const name of (await fs.readdir(folder)).sort()) {
      const relative = prefix + name;
      if (relative === MANIFEST) continue;
      const target = inside(root, relative),
        stat = await fs.lstat(target);
      if (stat.isSymbolicLink()) {
        const link = await fs.readlink(target);
        const resolved = path.resolve(path.dirname(target), link);
        if (
          path.isAbsolute(link) ||
          !resolved.startsWith(path.resolve(root) + path.sep)
        )
          throw new Error("A package link points outside the application.");
        const real = await fs.realpath(target);
        if (!real.startsWith(path.resolve(root) + path.sep))
          throw new Error("A package link resolves outside the application.");
        files[relative] = { link };
      } else if (stat.isDirectory()) await walk(target, relative + "/");
      else if (stat.isFile())
        files[relative] = {
          sha256: await fileHash(target),
          bytes: stat.size,
          executable: !!(stat.mode & 0o111),
        };
      else throw new Error("The application contains a special file.");
    }
  }
  await walk(root);
  return files;
}
async function createManifest(root, metadata) {
  const content = {
    format: 1,
    product: "DazedTL",
    profile_version: 1,
    ...metadata,
    files: await inventory(root),
  };
  const manifest = { ...content, id: hash(JSON.stringify(content)) };
  await fs.writeFile(path.join(root, MANIFEST), JSON.stringify(manifest));
  return manifest;
}
async function readManifest(root, full = false) {
  if ((await fs.lstat(root)).isSymbolicLink())
    throw new Error("Choose a regular application folder.");
  const manifestPath = path.join(root, MANIFEST);
  if (!(await fs.lstat(manifestPath)).isFile())
    throw new Error("Missing application package manifest.");
  const { id, ...content } = JSON.parse(
    await fs.readFile(manifestPath, "utf8"),
  );
  if (
    content.format !== 1 ||
    content.product !== "DazedTL" ||
    content.profile_version !== 1 ||
    hash(JSON.stringify(content)) !== id ||
    !content.files ||
    typeof content.version !== "string"
  )
    throw new Error("The package manifest is damaged or incompatible.");
  // Only the executable is resolved at startup. Validate the complete file
  // inventory when importing or activating a package, before it can be used.
  if (full) for (const name of Object.keys(content.files)) inside(root, name);
  const executable = inside(root, content.executable);
  if (
    !content.files[content.executable]?.sha256 ||
    !(await fs.stat(executable)).isFile()
  )
    throw new Error("The application executable is missing.");
  if (full) {
    const actual = await inventory(root);
    const mismatch = [
      ...new Set([...Object.keys(content.files), ...Object.keys(actual)]),
    ].find(
      (name) =>
        JSON.stringify(actual[name]) !== JSON.stringify(content.files[name]),
    );
    if (mismatch)
      throw new Error(
        `Application files changed or the package is incomplete: ${mismatch}`,
      );
  }
  return { ...content, id };
}
async function findPackage(executable) {
  let root = path.dirname(executable);
  for (let count = 0; count < 5; count++) {
    try {
      await fs.access(path.join(root, MANIFEST));
      return root;
    } catch {}
    root = path.dirname(root);
  }
  throw new Error(
    "This build has no update manifest. Install a complete desktop package.",
  );
}
module.exports = {
  MANIFEST,
  hash,
  fileHash,
  inside,
  inventory,
  createManifest,
  readManifest,
  findPackage,
};
