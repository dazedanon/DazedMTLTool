const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const {
  ApplicationUpdates,
  checkReleases,
} = require("../electron/updates.cjs");
const {
  createManifest,
  readManifest,
} = require("../electron/package-format.cjs");

async function fixture(t) {
  const root = await fs.mkdtemp(
    path.join(os.tmpdir(), "dazedtl-updates-test-"),
  );
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  async function application(name, version) {
    const folder = path.join(root, name);
    await fs.mkdir(folder);
    await fs.writeFile(path.join(folder, "dazedtl"), version, { mode: 0o755 });
    await createManifest(folder, {
      platform: process.platform,
      arch: process.arch,
      executable: "dazedtl",
      version,
    });
    return folder;
  }
  const first = await application("first", "1.0.0"),
    second = await application("second", "1.1.0");
  const profile = path.join(root, "profile");
  await fs.mkdir(path.join(profile, "workspace"), { recursive: true });
  await fs.writeFile(
    path.join(profile, "workspace", "saved-job.json"),
    "saved work and credentials fixture",
  );
  return {
    root,
    first,
    second,
    profile,
    manager: new ApplicationUpdates(profile, first),
  };
}

test("staging verifies the whole package and restart/rollback preserve the profile", async (t) => {
  const { first, second, profile, manager } = await fixture(t);
  await fs.writeFile(path.join(second, "unlisted-file"), "changed");
  await assert.rejects(manager.stage(second), /changed|incomplete/);
  await fs.unlink(path.join(second, "unlisted-file"));
  const wrongPlatform = new ApplicationUpdates(profile, first, "unsupported");
  await assert.rejects(wrongPlatform.stage(second), /operating system/);
  let state = await manager.stage(second);
  const candidate = state.staged[0];
  await assert.rejects(manager.select(candidate.id, "stale"), /changed/);
  await fs.writeFile(path.join(candidate.root, "dazedtl"), "damaged");
  await assert.rejects(
    manager.select(candidate.id, state.revision),
    /changed|incomplete/,
  );
  await fs.copyFile(
    path.join(second, "dazedtl"),
    path.join(candidate.root, "dazedtl"),
  );
  await manager.select(candidate.id, state.revision);
  const target = await manager.launchTarget();
  assert.equal(target.current, false);
  const upgraded = new ApplicationUpdates(profile, candidate.root);
  assert.equal((await upgraded.launchTarget(target.token)).current, true);
  await upgraded.healthy();
  state = await upgraded.state();
  assert.equal(state.pending, null);
  assert.equal(state.previous.root, first);
  await upgraded.select(state.previous.id, state.revision, true);
  const rollback = await upgraded.launchTarget();
  assert.equal((await manager.launchTarget(rollback.token)).current, true);
  await manager.healthy();
  assert.equal((await manager.state()).active.root, first);
  assert.equal(
    await fs.readFile(
      path.join(profile, "workspace", "saved-job.json"),
      "utf8",
    ),
    "saved work and credentials fixture",
  );
  assert.equal(await fs.readFile(path.join(first, "dazedtl"), "utf8"), "1.0.0");
  assert.equal(
    await fs.readFile(path.join(second, "dazedtl"), "utf8"),
    "1.1.0",
  );
});

test("an interrupted first launch returns to the previous application", async (t) => {
  const { first, second, manager } = await fixture(t);
  let state = await manager.stage(second);
  await manager.select(state.staged[0].id, state.revision);
  await manager.launchTarget();
  assert.equal((await manager.launchTarget()).current, true);
  state = await manager.state();
  assert.equal(state.active.root, first);
  assert.equal(state.pending, null);
  assert.match(state.message, /previous build was restored/);
  const manifest = path.join(second, "desktop-package.json");
  const value = JSON.parse(await fs.readFile(manifest));
  value.executable = "../outside";
  await fs.writeFile(manifest, JSON.stringify(value));
  await assert.rejects(readManifest(second), /damaged|incompatible/);
});

test("release checks select only a compatible complete package with a pinned checksum", async () => {
  const request = (releases) => async () => ({
    ok: true,
    json: async () => releases,
  });
  assert.equal(
    await checkReleases("linux", "x64", request([{ assets: [] }])),
    null,
  );
  const release = {
    tag_name: "desktop-v1",
    assets: [
      {
        name: "dazedtl-desktop-linux-x64.tar.gz",
        browser_download_url:
          "https://github.com/dazedanon/DazedMTLTool/releases/download/desktop-v1/application.tar.gz",
        digest: "sha256:" + "a".repeat(64),
        size: 42,
      },
    ],
  };
  assert.equal(
    (await checkReleases("linux", "x64", request([release]))).sha256,
    "a".repeat(64),
  );
  release.assets[0].browser_download_url =
    "https://unrelated.example/application.tar.gz";
  await assert.rejects(
    checkReleases("linux", "x64", request([release])),
    /verifiable/,
  );
  await assert.rejects(
    checkReleases("linux", "x64", async () => ({ ok: false, status: 503 })),
    /503/,
  );
});
