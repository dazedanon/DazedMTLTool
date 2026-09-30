const fs = (
  process.versions.electron ? require("original-fs") : require("node:fs")
).promises;
const path = require("node:path");
const { randomUUID } = require("node:crypto");
const { hash, inside, readManifest } = require("./package-format.cjs");

async function atomic(file, value) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const temporary = file + "." + randomUUID() + ".tmp";
  await fs.writeFile(temporary, JSON.stringify(value));
  await fs.rename(temporary, file);
}
class ApplicationUpdates {
  constructor(
    profile,
    current,
    platform = process.platform,
    arch = process.arch,
  ) {
    this.root = path.join(profile, "app-updates");
    this.current = path.resolve(current);
    this.platform = platform;
    this.arch = arch;
    this.file = path.join(this.root, "state.json");
    this.busy = false;
    this.currentRecord = null;
  }
  async installed() {
    // The running build is immutable. Candidate/rollback packages still get
    // a fresh complete byte check before every selection.
    if (!this.currentRecord) this.currentRecord = await this.record(this.current);
    return this.currentRecord;
  }
  async record(root, full = false) {
    const value = await readManifest(root, full);
    if (value.platform !== this.platform || value.arch !== this.arch)
      throw new Error(
        "Choose a package for this operating system and architecture.",
      );
    return {
      id: value.id,
      root: path.resolve(root),
      executable: value.executable,
      version: value.version,
      signed: value.signed === true,
    };
  }
  async load() {
    await fs.mkdir(this.root, { recursive: true });
    if ((await fs.realpath(this.root)) !== this.root)
      throw new Error(
        "Application update storage must not contain symbolic links.",
      );
    let state;
    try {
      state = JSON.parse(await fs.readFile(this.file, "utf8"));
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    if (!state)
      return {
        version: 1,
        active: await this.installed(),
        previous: null,
        staged: [],
        pending: null,
        message: "",
      };
    if (state.version !== 1 || !Array.isArray(state.staged))
      throw new Error("Unsupported application update state.");
    return state;
  }
  async state() {
    const value = await this.load();
    return {
      ...value,
      current: await this.installed(),
      revision: hash(JSON.stringify(value)),
      busy: this.busy,
    };
  }
  async exclusive(operation) {
    if (this.busy)
      throw new Error("Wait for the current application update action.");
    this.busy = true;
    try {
      return await operation();
    } finally {
      this.busy = false;
    }
  }
  async stage(source) {
    return this.exclusive(async () => {
      source = await fs.realpath(source);
      if (
        source === this.root ||
        source.startsWith(this.root + path.sep) ||
        this.root.startsWith(source + path.sep)
      )
        throw new Error(
          "Choose an application outside the update storage folder.",
        );
      const candidate = await this.record(source, true);
      const state = await this.load();
      if (candidate.id === state.active.id)
        throw new Error("This application build is already selected.");
      const target = path.join(this.root, "packages", candidate.id);
      await fs.mkdir(path.dirname(target), { recursive: true });
      if ((await fs.realpath(path.dirname(target))) !== path.dirname(target))
        throw new Error(
          "Application package storage must not use symbolic links.",
        );
      const temporary = target + "." + randomUUID() + ".staging";
      try {
        await fs.cp(source, temporary, {
          recursive: true,
          dereference: false,
          verbatimSymlinks: true,
        });
        const copied = await this.record(temporary, true);
        if (copied.id !== candidate.id)
          throw new Error("The selected package changed while copying.");
        try {
          await fs.access(target);
          await this.record(target, true);
        } catch (error) {
          if (error.code !== "ENOENT") throw error;
          await fs.rename(temporary, target);
        }
        state.staged = [
          ...state.staged.filter((item) => item.id !== candidate.id),
          { ...candidate, root: target },
        ];
        state.message = "Package verified and staged. Restart to activate it.";
        await atomic(this.file, state);
      } finally {
        await fs.rm(temporary, { recursive: true, force: true });
      }
      return this.state();
    });
  }
  async select(id, revision, rollback = false) {
    return this.exclusive(async () => {
      const state = await this.load();
      if (hash(JSON.stringify(state)) !== revision)
        throw new Error("Update choices changed. Refresh before restarting.");
      if (state.pending)
        throw new Error("Restart to finish the selected update first.");
      const target = rollback
        ? state.previous
        : state.staged.find((item) => item.id === id);
      if (!target || target.id === state.active.id)
        throw new Error("Choose a staged application or the previous build.");
      const checked = await this.record(target.root, true);
      if (checked.id !== target.id)
        throw new Error("The saved application changed. Import it again.");
      state.previous = state.active;
      state.active = checked;
      state.pending = { token: randomUUID(), attempted: false };
      state.message = rollback
        ? "Rollback selected; restart to finish."
        : "Update selected; restart to finish.";
      await atomic(this.file, state);
      return this.state();
    });
  }
  async launchTarget(token = "") {
    const state = await this.load();
    if (state.pending?.attempted && state.pending.token !== token) {
      if (!state.previous)
        throw new Error(
          "The new application did not finish starting and no previous build is available.",
        );
      const failed = state.active;
      state.active = state.previous;
      state.previous = failed;
      state.pending = null;
      state.message =
        "The new application did not finish starting. The previous build was restored.";
      await atomic(this.file, state);
    }
    try {
      const actual = state.active.root === this.current ? await this.installed() : await this.record(state.active.root);
      if (actual.id !== state.active.id)
        throw new Error("The selected application changed.");
    } catch (error) {
      if (!state.pending || !state.previous) throw error;
      state.active = state.previous;
      state.previous = null;
      state.pending = null;
      state.message =
        "The selected package was unavailable. The previous build was restored.";
      await atomic(this.file, state);
    }
    if (state.pending && !state.pending.attempted) {
      state.pending.attempted = true;
      await atomic(this.file, state);
    }
    return {
      executable: inside(state.active.root, state.active.executable),
      token: state.pending?.token || "",
      current: state.active.root === this.current,
    };
  }
  async healthy() {
    const state = await this.load();
    if (state.pending && state.active.root === this.current) {
      state.pending = null;
      state.message =
        "The selected application started successfully. The previous build is available for rollback.";
      await atomic(this.file, state);
    }
  }
}

const RELEASES =
  "https://api.github.com/repos/dazedanon/DazedMTLTool/releases?per_page=20";
async function checkReleases(
  platform = process.platform,
  arch = process.arch,
  transport = fetch,
) {
  const response = await transport(RELEASES, {
    headers: { Accept: "application/vnd.github+json", "User-Agent": "DazedTL" },
    signal: AbortSignal.timeout(20000),
  });
  if (!response.ok)
    throw new Error(`Could not check desktop releases (${response.status}).`);
  const releases = await response.json();
  if (!Array.isArray(releases))
    throw new Error("Invalid desktop release response.");
  const name = `dazedtl-desktop-${platform}-${arch}.tar.gz`;
  for (const release of releases) {
    if (release.draft || release.prerelease) continue;
    const asset = (release.assets || []).find((item) => item.name === name);
    if (!asset) continue;
    if (
      !/^https:\/\/github\.com\/dazedanon\/DazedMTLTool\/releases\/download\//.test(
        asset.browser_download_url,
      ) ||
      !/^sha256:[a-f0-9]{64}$/.test(asset.digest || "")
    )
      throw new Error(
        "This release has no verifiable desktop package. Download and inspect it separately.",
      );
    return {
      tag: String(release.tag_name),
      name,
      url: asset.browser_download_url,
      sha256: asset.digest.slice(7),
      bytes: asset.size,
    };
  }
  return null;
}
module.exports = { ApplicationUpdates, checkReleases, atomic };
