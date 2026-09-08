#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

function usage() {
  console.log("Usage: node decrypt_rpgmz_data.js --game <game folder> [--out decrypted_data] [--pretty]");
}

function parseArgs(argv) {
  const args = { gameDir: null, outDir: "decrypted_data", pretty: false };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--game") {
      if (!argv[i + 1]) throw new Error("--game requires the game folder");
      args.gameDir = argv[++i];
    } else if (arg === "--out") {
      if (!argv[i + 1]) throw new Error("--out requires a directory");
      args.outDir = argv[++i];
    } else if (arg === "--pretty") {
      args.pretty = true;
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
  if (!fs.existsSync(path.join(gameRoot, "data"))) {
    throw new Error(`Could not find data/ in game folder: ${gameRoot}`);
  }
  if (!fs.existsSync(path.join(gameRoot, "js", "rmmz_core.dat"))) {
    throw new Error(`Could not find js/rmmz_core.dat in game folder: ${gameRoot}`);
  }
  return gameRoot;
}

function resolveFromGameRoot(gameRoot, filePath) {
  return path.isAbsolute(filePath) ? filePath : path.join(gameRoot, filePath);
}

function isWrappedDataFile(filePath) {
  try {
    const parsed = JSON.parse(fs.readFileSync(filePath, "utf8"));
    return parsed && typeof parsed.data === "string" && /^[0-9a-f]+$/i.test(parsed.data);
  } catch {
    return false;
  }
}

function loadDecryptor(gameRoot, maxPayloadLength) {
  const wasmPath = path.join(gameRoot, "js", "rmmz_core.dat");
  const wasm = fs.readFileSync(wasmPath);
  const pages = Math.max(1, Math.ceil(maxPayloadLength / 65536) + 1);
  const memory = new WebAssembly.Memory({ initial: pages });
  const module = new WebAssembly.Module(wasm);
  const instance = new WebAssembly.Instance(module, { env: { memory } });

  if (typeof instance.exports.f3 !== "function") {
    throw new Error(`${wasmPath} does not export f3`);
  }

  return {
    memory,
    decrypt(raw, key) {
      const view = new Uint8Array(memory.buffer);
      view.set(raw, 0);
      instance.exports.f3(0, raw.length, key);
      return Buffer.from(view.slice(0, raw.length));
    },
  };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const gameRoot = resolveGameRoot(args.gameDir);
  const dataDir = path.join(gameRoot, "data");
  const outDir = resolveFromGameRoot(gameRoot, args.outDir);

  const files = fs
    .readdirSync(dataDir)
    .filter((name) => name.endsWith(".json"))
    .map((name) => path.join(dataDir, name))
    .filter(isWrappedDataFile);

  if (files.length === 0) {
    throw new Error("No wrapped encrypted data/*.json files found");
  }

  const wrapped = files.map((filePath) => {
    const envelope = JSON.parse(fs.readFileSync(filePath, "utf8"));
    const raw = Buffer.from(envelope.data, "hex");
    const key = Number.parseInt(envelope.uid, 16);
    if (!Number.isInteger(key)) {
      throw new Error(`${filePath} has no hexadecimal uid key`);
    }
    return { filePath, raw, key };
  });

  const maxPayloadLength = Math.max(...wrapped.map((entry) => entry.raw.length));
  const decryptor = loadDecryptor(gameRoot, maxPayloadLength);

  fs.mkdirSync(outDir, { recursive: true });

  let ok = 0;
  for (const { filePath, raw, key } of wrapped) {
    const decrypted = decryptor.decrypt(raw, key);
    const text = decrypted.toString("utf8").replace(/^\uFEFF/, "");
    const parsed = JSON.parse(text);
    const output = args.pretty ? JSON.stringify(parsed, null, 2) + "\n" : text;
    fs.writeFileSync(path.join(outDir, path.basename(filePath)), output, "utf8");
    ok++;
  }

  console.log(`Decrypted ${ok} files into ${outDir}`);
}

try {
  main();
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
