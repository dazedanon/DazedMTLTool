'use strict';

// Run with the game's bundled Electron in ELECTRON_RUN_AS_NODE mode.
// original-fs is essential: normal Electron fs transparently opens ASAR members.
const fs = require('original-fs');
const path = require('path');
const crypto = require('crypto');
const cp = require('child_process');
const assert = require('assert');
const CHUNK = 4 * 1024 * 1024;
const FORMAT = 1;
const EXE = 'musi_dream.exe';
const HEX = /^[a-f0-9]{64}$/;

function fail(message) { throw new Error(message); }
function hash(data) { return crypto.createHash('sha256').update(data).digest('hex'); }
function fileHash(file) {
  const fd = fs.openSync(file, 'r');
  const digest = crypto.createHash('sha256');
  const buffer = Buffer.alloc(CHUNK);
  try {
    let n;
    while ((n = fs.readSync(fd, buffer, 0, buffer.length, null))) digest.update(buffer.subarray(0, n));
    return digest.digest('hex');
  } finally { fs.closeSync(fd); }
}
function readAt(fd, size, position) {
  const buffer = Buffer.alloc(size);
  let done = 0;
  while (done < size) {
    const n = fs.readSync(fd, buffer, done, size - done, position + done);
    if (!n) fail('Unexpected end of archive.');
    done += n;
  }
  return buffer;
}
function writeAll(fd, buffer) {
  let done = 0;
  while (done < buffer.length) done += fs.writeSync(fd, buffer, done, buffer.length - done);
}
function safeRel(rel) {
  if (typeof rel !== 'string' || !rel || rel.includes('\\') || rel.includes(':') ||
      rel.includes('\0') || rel.split('/').some(x => !x || x === '.' || x === '..')) {
    fail('Unsafe archive or payload path: ' + JSON.stringify(rel));
  }
  return rel;
}
function inside(root, candidate) {
  const rel = path.relative(root, candidate);
  if (!rel || rel === '..' || rel.startsWith('..' + path.sep) || path.isAbsolute(rel)) {
    fail('Path must remain inside its designated directory: ' + candidate);
  }
  return candidate;
}
function existingFile(root, rel) {
  safeRel(rel);
  const target = inside(root, fs.realpathSync(path.join(root, ...rel.split('/'))));
  if (!fs.statSync(target).isFile()) fail('Expected a regular file: ' + target);
  return target;
}
function integer(value, label) {
  if (!Number.isSafeInteger(value) || value < 0) fail('Invalid ' + label);
  return value;
}
function entries(header) {
  const result = [];
  function walk(node, prefix) {
    if (!node.files || typeof node.files !== 'object' || Array.isArray(node.files)) fail('Invalid ASAR directory.');
    for (const [name, entry] of Object.entries(node.files)) {
      if (name.includes('/') || name.includes('\\')) fail('Invalid ASAR entry name.');
      const rel = safeRel(prefix ? prefix + '/' + name : name);
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) fail('Invalid ASAR entry: ' + rel);
      if (entry.files) walk(entry, rel);
      else {
        if (entry.link || entry.unpacked) fail('Unsupported linked or unpacked ASAR entry: ' + rel);
        integer(entry.size, 'ASAR size');
        if (typeof entry.offset !== 'string' || !/^\d+$/.test(entry.offset)) fail('Invalid ASAR offset.');
        integer(Number(entry.offset), 'ASAR offset');
        result.push({ rel, entry, offset: Number(entry.offset), size: entry.size });
      }
    }
  }
  walk(header, '');
  return result;
}
function readArchive(file) {
  const fd = fs.openSync(file, 'r');
  try {
    const size = fs.fstatSync(fd).size;
    const prefix = readAt(fd, 8, 0);
    if (prefix.readUInt32LE(0) !== 4) fail('Not an ASAR archive: ' + file);
    const headerSize = prefix.readUInt32LE(4);
    if (headerSize < 8 || headerSize > 64 * 1024 * 1024 || headerSize + 8 > size) fail('Invalid ASAR header size.');
    const pickle = readAt(fd, headerSize, 8);
    const jsonSize = pickle.readUInt32LE(4);
    if (pickle.readUInt32LE(0) !== headerSize - 4 || jsonSize > headerSize - 8) fail('Invalid ASAR header pickle.');
    const header = JSON.parse(pickle.subarray(8, 8 + jsonSize).toString('utf8'));
    const records = entries(header);
    const dataOffset = 8 + headerSize;
    for (const record of records) {
      if (dataOffset + record.offset + record.size > size) fail('ASAR entry extends beyond archive: ' + record.rel);
    }
    return { file, header, records, dataOffset, size };
  } finally { fs.closeSync(fd); }
}
function headerBytes(header) {
  const json = Buffer.from(JSON.stringify(header), 'utf8');
  const padded = Math.ceil(json.length / 4) * 4;
  const output = Buffer.alloc(16 + padded);
  output.writeUInt32LE(4, 0);
  output.writeUInt32LE(8 + padded, 4);
  output.writeUInt32LE(4 + padded, 8);
  output.writeUInt32LE(json.length, 12);
  json.copy(output, 16);
  return output;
}
function integrity(fd, position, size, template) {
  const blockSize = template ? template.blockSize : CHUNK;
  if (template && template.algorithm !== 'SHA256') fail('Unsupported ASAR integrity algorithm.');
  if (!Number.isSafeInteger(blockSize) || blockSize <= 0 || blockSize > 64 * 1024 * 1024) fail('Invalid integrity block size.');
  const whole = crypto.createHash('sha256');
  const blocks = [];
  for (let done = 0; done < size; done += blockSize) {
    const block = readAt(fd, Math.min(blockSize, size - done), position + done);
    whole.update(block);
    blocks.push(hash(block));
  }
  // ASAR's stream hashing produces one digest for a zero-byte file.
  if (size === 0) blocks.push(hash(Buffer.alloc(0)));
  return { ...(template || {}), algorithm: 'SHA256', hash: whole.digest('hex'), blockSize, blocks };
}
function loadPackage(packageRoot) {
  const manifestPath = existingFile(packageRoot, 'manifest.json');
  const bytes = fs.readFileSync(manifestPath);
  const manifest = JSON.parse(bytes.toString('utf8').replace(/^\uFEFF/, ''));
  if (manifest.format_version !== FORMAT || manifest.game_executable !== EXE || !HEX.test(manifest.original_sha256)) fail('Unsupported or invalid patch manifest.');
  if (manifest.patched_sha256 !== undefined && !HEX.test(manifest.patched_sha256)) fail('Invalid patched_sha256.');
  if (!manifest.files || typeof manifest.files !== 'object' || Array.isArray(manifest.files) || !Object.keys(manifest.files).length) fail('The manifest has no replacement files.');
  const payloadRoot = inside(packageRoot, fs.realpathSync(path.join(packageRoot, 'payload')));
  const replacements = new Map();
  const folded = new Set();
  for (const [rel, expected] of Object.entries(manifest.files)) {
    safeRel(rel);
    if (!HEX.test(expected)) fail('Invalid payload SHA256: ' + rel);
    if (folded.has(rel.toLowerCase())) fail('Case-colliding payload paths: ' + rel);
    folded.add(rel.toLowerCase());
    const file = existingFile(payloadRoot, rel);
    if (fileHash(file) !== expected) fail('Payload checksum mismatch: ' + rel);
    replacements.set(rel, { file, sha256: expected, size: fs.statSync(file).size });
  }
  return { manifest, replacements, manifestSha256: hash(bytes) };
}
function planArchive(original, replacements) {
  const header = JSON.parse(JSON.stringify(original.header));
  const changed = entries(header);
  const source = new Map(original.records.map(x => [x.rel, x]));
  for (const rel of replacements.keys()) if (!source.has(rel)) fail('Payload entry is absent from the original archive: ' + rel);
  let offset = 0;
  for (const record of changed) {
    const replacement = replacements.get(record.rel);
    record.sourceOffset = source.get(record.rel).offset;
    record.sourceSize = source.get(record.rel).size;
    if (replacement) {
      const fd = fs.openSync(replacement.file, 'r');
      try { record.entry.integrity = integrity(fd, 0, replacement.size, record.entry.integrity); }
      finally { fs.closeSync(fd); }
      if (record.entry.integrity.hash !== replacement.sha256) fail('Payload changed while preparing: ' + record.rel);
      record.entry.size = replacement.size;
    }
    record.entry.offset = String(offset);
    record.offset = offset;
    record.size = record.entry.size;
    offset += record.size;
    integer(offset, 'total ASAR data size');
  }
  return { header, records: changed, prefix: headerBytes(header), dataSize: offset };
}
function copyBytes(srcFd, dstFd, position, size) {
  for (let done = 0; done < size; done += CHUNK) {
    writeAll(dstFd, readAt(srcFd, Math.min(CHUNK, size - done), position + done));
  }
}
function writeArchive(original, plan, replacements, output) {
  const srcFd = fs.openSync(original.file, 'r');
  let dstFd;
  try {
    dstFd = fs.openSync(output, 'wx');
    writeAll(dstFd, plan.prefix);
    for (const record of plan.records) {
      const replacement = replacements.get(record.rel);
      if (replacement) {
        const fd = fs.openSync(replacement.file, 'r');
        try { copyBytes(fd, dstFd, 0, replacement.size); }
        finally { fs.closeSync(fd); }
      } else copyBytes(srcFd, dstFd, original.dataOffset + record.sourceOffset, record.sourceSize);
    }
    fs.fsyncSync(dstFd);
  } finally {
    if (dstFd !== undefined) fs.closeSync(dstFd);
    fs.closeSync(srcFd);
  }
}
function verifyArchive(file, original, plan, replacements) {
  const rebuilt = readArchive(file);
  assert.deepStrictEqual(rebuilt.header, plan.header, 'Rebuilt ASAR header differs from the planned header.');
  if (rebuilt.size !== plan.prefix.length + plan.dataSize) fail('Unexpected rebuilt archive length.');
  const oldFd = fs.openSync(original.file, 'r');
  const newFd = fs.openSync(file, 'r');
  try {
    for (const record of plan.records) {
      const replacement = replacements.get(record.rel);
      const actual = integrity(newFd, rebuilt.dataOffset + record.offset, record.size, record.entry.integrity);
      if (record.entry.integrity) assert.deepStrictEqual(actual, record.entry.integrity, 'Integrity mismatch: ' + record.rel);
      if (replacement) {
        if (actual.hash !== replacement.sha256) fail('Replacement differs from payload: ' + record.rel);
      } else {
        const expected = integrity(oldFd, original.dataOffset + record.sourceOffset, record.sourceSize, record.entry.integrity);
        if (actual.hash !== expected.hash) fail('Untouched entry differs from original: ' + record.rel);
      }
    }
  } finally { fs.closeSync(oldFd); fs.closeSync(newFd); }
  return { sha256: fileHash(file), entries: plan.records.length, replacements: replacements.size, bytes: rebuilt.size };
}
function checkGameClosed(executable) {
  if (process.platform !== 'win32') fail('This installer supports the Windows game build only.');
  const script = "$ErrorActionPreference='Stop'; $matches=@(Get-Process | Where-Object { $_.ProcessName -eq 'musi_dream' -and $_.Id -ne [int]$env:MUSI_PATCH_SELF_PID -and ((-not $_.Path) -or [String]::Equals($_.Path,$env:MUSI_PATCH_GAME_EXE,[StringComparison]::OrdinalIgnoreCase)) }); if ($matches.Count) { $matches | ForEach-Object { Write-Output ('Game process '+$_.Id+' is running. Close it before continuing.') }; exit 2 }";
  const result = cp.spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-EncodedCommand', Buffer.from(script, 'utf16le').toString('base64')], {
    windowsHide: true, encoding: 'utf8', timeout: 30000,
    env: { ...process.env, MUSI_PATCH_GAME_EXE: executable, MUSI_PATCH_SELF_PID: String(process.pid) }
  });
  if (result.error || result.status !== 0) fail((result.stdout || result.stderr || String(result.error) || 'Could not check running game processes.').trim());
}
function args() {
  const values = {};
  const allowed = new Set(['mode', 'game-root', 'package-root', 'output']);
  for (let i = 2; i < process.argv.length; i += 2) {
    const key = process.argv[i];
    if (!key.startsWith('--') || !allowed.has(key.slice(2)) || !process.argv[i + 1] || values[key.slice(2)] !== undefined) fail('Invalid command arguments. Use install.ps1 or restore.ps1.');
    values[key.slice(2)] = process.argv[i + 1];
  }
  if (!['build', 'install', 'restore'].includes(values.mode) || !values['game-root']) fail('A mode and game root are required.');
  if (values.mode === 'build' && !values.output) fail('Build mode requires --output.');
  if (values.mode !== 'build' && values.output) fail('--output is only available in build mode.');
  return values;
}
function main() {
  const options = args();
  const gameRoot = fs.realpathSync(path.resolve(options['game-root']));
  const packageRoot = fs.realpathSync(path.resolve(options['package-root'] || __dirname));
  const executable = existingFile(gameRoot, EXE);
  const resources = inside(gameRoot, fs.realpathSync(path.join(gameRoot, 'resources')));
  const archive = existingFile(gameRoot, 'resources/app.asar');
  const backup = inside(resources, path.join(resources, 'app.asar.original'));
  const pkg = loadPackage(packageRoot);
  if (options.mode !== 'build') checkGameClosed(executable);
  const currentHash = fileHash(archive);
  let originalPath = archive;
  if (fs.existsSync(backup)) {
    existingFile(gameRoot, 'resources/app.asar.original');
    if (fileHash(backup) !== pkg.manifest.original_sha256) fail('Original backup checksum is unknown. No game files were changed.');
    originalPath = backup;
  } else if (currentHash !== pkg.manifest.original_sha256) fail('This archive is not the supported original, and no verified original backup exists.');
  if (options.mode === 'restore' && currentHash === pkg.manifest.original_sha256) {
    console.log(JSON.stringify({ mode: 'restore', status: 'already-original', archive, sha256: currentHash }, null, 2));
    return;
  }
  const original = readArchive(originalPath);
  const plan = planArchive(original, pkg.replacements);
  if (currentHash !== pkg.manifest.original_sha256) {
    try { verifyArchive(archive, original, plan, pkg.replacements); }
    catch (error) { fail('Current archive is neither the supported original nor this exact patch. No game files were changed. ' + error.message); }
    if (pkg.manifest.patched_sha256 && currentHash !== pkg.manifest.patched_sha256) fail('Installed patch checksum is different from the manifest.');
    if (options.mode === 'install') {
      console.log(JSON.stringify({ mode: 'install', status: 'already-installed', archive, sha256: currentHash }, null, 2));
      return;
    }
  }
  const suffix = process.pid + '-' + crypto.randomBytes(6).toString('hex');
  let output;
  if (options.mode === 'build') {
    const requested = path.resolve(options.output);
    const parent = fs.realpathSync(path.dirname(requested));
    output = inside(gameRoot, path.join(parent, path.basename(requested)));
    if (output.toLowerCase() === archive.toLowerCase() || output.toLowerCase() === backup.toLowerCase()) fail('Build output must not be the installed archive or backup.');
  } else output = inside(resources, path.join(resources, 'app.asar.' + options.mode + '-' + suffix + '.tmp'));
  if (fs.existsSync(output)) fail('Output already exists; choose a new path: ' + output);
  let report;
  if (options.mode === 'restore') {
    fs.copyFileSync(backup, output, fs.constants.COPYFILE_EXCL);
    if (fileHash(output) !== pkg.manifest.original_sha256) fail('Restore candidate checksum mismatch.');
    const fd = fs.openSync(output, 'r+');
    try { fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    report = { sha256: pkg.manifest.original_sha256, bytes: fs.statSync(output).size };
  } else {
    writeArchive(original, plan, pkg.replacements, output);
    report = verifyArchive(output, original, plan, pkg.replacements);
    if (pkg.manifest.patched_sha256 && report.sha256 !== pkg.manifest.patched_sha256) fail('Built patch checksum differs from the manifest.');
  }
  // A changed source or payload during the build must never be installed.
  if (fileHash(originalPath) !== pkg.manifest.original_sha256) fail('Original archive changed during the operation.');
  for (const [rel, item] of pkg.replacements) if (fileHash(item.file) !== item.sha256) fail('Payload changed during the operation: ' + rel);
  if (options.mode !== 'build') {
    checkGameClosed(executable);
    if (fileHash(archive) !== currentHash) fail('Installed archive changed during the operation.');
    if (options.mode === 'install' && !fs.existsSync(backup)) {
      fs.copyFileSync(archive, backup, fs.constants.COPYFILE_EXCL);
      if (fileHash(backup) !== pkg.manifest.original_sha256) fail('Original backup could not be verified.');
    }
    // Same-directory rename replaces only the verified archive atomically.
    // A locked archive makes rename fail; the verified backup remains intact.
    fs.renameSync(output, archive);
    output = archive;
    if (fileHash(archive) !== report.sha256) fail('Post-install archive checksum mismatch; verified backup remains at ' + backup);
  }
  console.log(JSON.stringify({ mode: options.mode, status: 'ok', output, backup: options.mode === 'build' ? null : backup,
    original_sha256: pkg.manifest.original_sha256, manifest_sha256: pkg.manifestSha256, ...report }, null, 2));
}
try { main(); }
catch (error) {
  console.error('Patch operation stopped: ' + error.message);
  console.error('No user files are deleted. Any uniquely named candidate file is retained for inspection.');
  process.exitCode = 1;
}
