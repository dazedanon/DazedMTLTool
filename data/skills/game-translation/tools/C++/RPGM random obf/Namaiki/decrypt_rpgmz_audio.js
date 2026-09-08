#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const RPGM_HEADER = Buffer.from("5250474d560000000003010000000000", "hex");

function usage() {
  console.log("Usage: node decrypt_rpgmz_audio.js --game <game folder> [--out runtime_dump_assets]");
}

function parseArgs(argv) {
  const args = { gameDir: null, outDir: "runtime_dump_assets" };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--game") {
      if (!argv[i + 1]) throw new Error("--game requires the game folder");
      args.gameDir = argv[++i];
    } else if (arg === "--out") {
      if (!argv[i + 1]) throw new Error("--out requires a directory");
      args.outDir = argv[++i];
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
  if (!fs.existsSync(path.join(gameRoot, "audio"))) {
    throw new Error(`Could not find audio/ in game folder: ${gameRoot}`);
  }
  if (!fs.existsSync(path.join(gameRoot, "decrypted_data", "System.json"))) {
    throw new Error(`Could not find decrypted_data/System.json in game folder: ${gameRoot}`);
  }
  return gameRoot;
}

function resolveFromGameRoot(gameRoot, filePath) {
  return path.isAbsolute(filePath) ? filePath : path.join(gameRoot, filePath);
}

function walkFiles(dir) {
  const out = [];
  if (!fs.existsSync(dir)) return out;

  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...walkFiles(fullPath));
    } else if (entry.isFile()) {
      out.push(fullPath);
    }
  }

  return out;
}

function outputPathFor(gameRoot, filePath, outDir) {
  const relative = path.relative(gameRoot, filePath);
  const cleanName = relative.endsWith("_") ? relative.slice(0, -1) : relative;
  return path.join(outDir, cleanName);
}

function decryptAudio(filePath, key) {
  const encrypted = fs.readFileSync(filePath);
  if (encrypted.length < RPGM_HEADER.length || !encrypted.subarray(0, RPGM_HEADER.length).equals(RPGM_HEADER)) {
    throw new Error(`${filePath} does not have an RPG Maker encrypted asset header`);
  }

  const decrypted = Buffer.from(encrypted.subarray(RPGM_HEADER.length));
  for (let i = 0; i < key.length && i < decrypted.length; i++) {
    decrypted[i] ^= key[i];
  }
  return decrypted;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const gameRoot = resolveGameRoot(args.gameDir);
  const outDir = resolveFromGameRoot(gameRoot, args.outDir);
  const systemPath = path.join(gameRoot, "decrypted_data", "System.json");

  if (!fs.existsSync(systemPath)) {
    throw new Error("Missing decrypted_data/System.json; run decrypt_rpgmz_data.js first");
  }

  const system = JSON.parse(fs.readFileSync(systemPath, "utf8"));
  const key = Buffer.from(system.encryptionKey, "hex");
  if (key.length !== 16) {
    throw new Error("System.json encryptionKey is not 16 bytes");
  }

  const files = walkFiles(path.join(gameRoot, "audio")).filter((filePath) => filePath.endsWith("_"));
  if (files.length === 0) {
    throw new Error("No encrypted audio files found under audio/");
  }

  let ok = 0;
  for (const filePath of files) {
    const outPath = outputPathFor(gameRoot, filePath, outDir);
    fs.mkdirSync(path.dirname(outPath), { recursive: true });
    fs.writeFileSync(outPath, decryptAudio(filePath, key));
    ok++;
  }

  console.log(`Decrypted ${ok} audio files into ${outDir}`);
}

try {
  main();
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
