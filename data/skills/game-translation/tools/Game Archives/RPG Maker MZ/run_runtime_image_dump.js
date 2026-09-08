#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const childProcess = require("child_process");
const { pathToFileURL } = require("url");

function usage() {
  console.log("Usage: node run_runtime_image_dump.js --game <game folder>");
}

function parseArgs(argv) {
  const args = { gameDir: null };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--game") {
      if (!argv[i + 1]) throw new Error("--game requires the game folder");
      args.gameDir = argv[++i];
    } else if (arg === "-h" || arg === "--help") {
      usage();
      process.exit(0);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return args;
}

function defaultGameRoot() {
  return path.resolve(__dirname, "..");
}

function resolveGameRoot(gameDir) {
  const gameRoot = path.resolve(gameDir || defaultGameRoot());
  if (!fs.existsSync(path.join(gameRoot, "Game.exe"))) {
    throw new Error(`Could not find Game.exe in game folder: ${gameRoot}`);
  }
  if (!fs.existsSync(path.join(gameRoot, "package.json"))) {
    throw new Error(`Could not find package.json in game folder: ${gameRoot}`);
  }
  return gameRoot;
}

const args = parseArgs(process.argv.slice(2));
const rootDir = resolveGameRoot(args.gameDir);
const packagePath = path.join(rootDir, "package.json");
const packageBackupPath = path.join(rootDir, "package.json.bak");
const gamePath = path.join(rootDir, "Game.exe");
const dumpPage = ".runtime_image_dump.html";
const dumpPagePath = path.join(rootDir, dumpPage);
const runtimeScriptPath = path.join(__dirname, "runtime_image_dump.js");
const runtimePageTemplatePath = path.join(__dirname, "runtime_image_dump.html");
const currentPackage = fs.readFileSync(packagePath, "utf8");
const currentPackageJson = JSON.parse(currentPackage);
const dumpMains = new Set([dumpPage, "tools/runtime_image_dump.html"]);
const originalPackage =
  dumpMains.has(currentPackageJson.main) && fs.existsSync(packageBackupPath)
    ? fs.readFileSync(packageBackupPath, "utf8")
    : currentPackage;
let restored = false;

function restorePackage() {
  if (restored) return;
  fs.writeFileSync(packagePath, originalPackage);
  try {
    if (fs.existsSync(dumpPagePath)) fs.unlinkSync(dumpPagePath);
  } catch {
    // The package restore matters more than deleting the temporary page.
  }
  restored = true;
}

function fail(message) {
  restorePackage();
  console.error(message);
  process.exit(1);
}

if (!fs.existsSync(gamePath)) {
  fail(`Missing ${gamePath}`);
}

if (!fs.existsSync(runtimeScriptPath)) {
  fail(`Missing ${runtimeScriptPath}`);
}

if (!fs.existsSync(runtimePageTemplatePath)) {
  fail(`Missing ${runtimePageTemplatePath}`);
}

const gameBasePath = rootDir.endsWith(path.sep) ? rootDir : rootDir + path.sep;
const dumpHtml = fs
  .readFileSync(runtimePageTemplatePath, "utf8")
  .split("{{GAME_BASE_URL}}").join(pathToFileURL(gameBasePath).href)
  .split("{{RUNTIME_SCRIPT_URL}}").join(pathToFileURL(runtimeScriptPath).href);

fs.writeFileSync(packageBackupPath, originalPackage);
fs.writeFileSync(dumpPagePath, dumpHtml, "utf8");

const pkg = JSON.parse(originalPackage);
pkg.main = dumpPage;
fs.writeFileSync(packagePath, JSON.stringify(pkg, null, 4) + "\n");

const child = childProcess.spawn(gamePath, [], {
  cwd: rootDir,
  stdio: "ignore",
  windowsHide: true
});

child.on("error", error => {
  restorePackage();
  console.error(error.stack || error.message);
  process.exit(1);
});

child.on("exit", code => {
  restorePackage();
  process.exit(code || 0);
});

process.on("SIGINT", () => {
  restorePackage();
  process.exit(130);
});

process.on("SIGTERM", () => {
  restorePackage();
  process.exit(143);
});

process.on("uncaughtException", error => {
  restorePackage();
  console.error(error.stack || error.message);
  process.exit(1);
});

process.on("unhandledRejection", error => {
  restorePackage();
  console.error(error && (error.stack || error.message) || error);
  process.exit(1);
});

process.on("exit", restorePackage);
