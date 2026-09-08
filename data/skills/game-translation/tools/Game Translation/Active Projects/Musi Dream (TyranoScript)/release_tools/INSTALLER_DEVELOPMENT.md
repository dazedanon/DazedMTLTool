# Installer development notes

This file and the `selftest*` files/directories are developer material. `scripts/package.py` distributes only `install.ps1`, `restore.ps1`, `invoke-patch.ps1`, `patch.cjs`, `README.md`, the generated manifest, and its payload.

## Build without installing

Choose a new output filename whose parent already exists inside the game directory:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -GameRoot 'C:\path\to\musi_dream-win32-x64' -BuildOnly -Output 'C:\path\to\musi_dream-win32-x64\translation\build\app.asar'
```

Build-only mode reads the original archive and payload without installing changes. The game may be running during this mode. Installation and restoration check the target executable path for running processes before the operation and immediately before replacement.

The PowerShell wrapper temporarily sets `ELECTRON_RUN_AS_NODE=1` and restores the prior environment state in `finally`. Piping the bundled Windows GUI executable through `Out-Host` makes PowerShell wait for completion and report its native exit code. `patch.cjs` uses Electron's `original-fs` so ASAR archive reads access raw bytes.

## Manifest

The package contains UTF-8 `manifest.json` and files under `payload/` at their archive-relative paths:

```json
{
  "format_version": 1,
  "game_executable": "musi_dream.exe",
  "original_sha256": "64 lowercase hexadecimal characters",
  "files": {
    "data/scenario/example.ks": "SHA256 of payload/data/scenario/example.ks"
  }
}
```

An optional `patched_sha256` pins the deterministic rebuilt archive. Replacement paths must name existing packed archive entries, use forward slashes, and stay inside the payload directory. Symlinks escaping either the game directory or package directory are rejected. New archive entries, unpacked files, and ASAR links are unsupported for this build.

## Reviewed image inputs

Image localization uses the same existing-entry replacement mechanism. The build reads `images/manifest.json` in the translation project, with pristine images under `images/source/` and localized images under `images/output/`, each preserving its archive-relative path. The manifest has this structure:

```json
{
  "format_version": 1,
  "original_archive_sha256": "0427999aee3dd5e6e6cc995eca1f6cf7a1a94bdc43222a247bc103a99a12b524",
  "inventory_status": "reviewed",
  "coverage_ref": "images/coverage.json",
  "assets": [
    {
      "path": "data/image/example.png",
      "source_sha256": "SHA256 of the pristine image",
      "output_sha256": "SHA256 of the reviewed localized image",
      "width": 1280,
      "height": 720,
      "mode": "RGBA",
      "status": "rendered",
      "reviewed": true,
      "source_format": "PNG",
      "output_format": "PNG"
    }
  ]
}
```

Only translated assets appear in `assets`; the separate inventory covers all inspected images. The build verifies the whole original archive checksum, each pristine image against its packed entry, reviewed source/output checksums, safe unique existing paths, dimensions, mode, and one-frame geometry. It rejects unlisted files in `images/output`. Format metadata is optional; if present, it must match Pillow's decoded format. Lossless PNG content may retain an original `.jpg` filename because Chromium detects the content format. This avoids recompressing untouched pixels, and must also be checked in the actual game.

`reports/build.json` binds each image to the image-manifest checksum and payload checksum. `scripts/final_report.py` requires `reports/image_runtime.json` whenever localized images are shipped, with `passed: true`, `archive_sha256` matching the installed archive, and `image_manifest_sha256` matching the current manifest. Detailed screen checks and screenshots belong in that runtime report. The build checks geometry and provenance; visual review establishes transcription, meaning, erasure, and art preservation.

Before replacing a previous release, preserve its package so its restoration manifest remains available. The first text-only release is retained under `history/release-text-only/`. Restore the previous revision with its own package before installing a new revision. `scripts/sync_project.py` includes the complete image workspace in the durable Tools project; only the reviewed output files enter the player patch.

## Repacking and restoration

The ASAR streaming and immutable source-offset approach adapts `Reference Pipelines/TyranoScript (AjinSyoujyo)/scripts/tyranotl/deploy.py`. This implementation uses the actual archive pickle lengths from Musi Dream's shipped archive. It does not use that reference pipeline's loader shim.

Every original entry offset is captured before header updates. Unchanged entry contents and metadata are preserved. Replaced entries receive new sizes, offsets, and SHA256 block hashes while retaining other metadata. Before installation, the candidate header, every payload and unchanged entry, integrity blocks, and complete archive checksum are verified. A same-directory atomic rename replaces only the verified installed archive; the original is retained at `resources/app.asar.original`.

An unknown archive is rejected. Reinstallation accepts only the supported original or the exact patch built from the current manifest. Restoration verifies the original backup and accepts only that exact installed patch or an already restored original. Successful operations print JSON with checksums. Uniquely named temporary candidates are retained after failures; the installer does not delete files. A final post-install checksum detects any filesystem failure after replacement, while the original backup remains available.

## Regression checks

Run `python selftest.py` from the development workspace. The test creates a small isolated archive fixture, including source offsets in a different order from header traversal, and exercises build, installation, repeated installation, restoration, modified-payload and archive rejection, unsafe paths, existing output protection, process detection, and wrapper environment restoration. It does not install into the real game directory. The self-test needs Python; the shipped installer does not.

In this workspace's restricted sandbox, Electron's child PowerShell process check may require an escalated test invocation. That is an execution-environment restriction, not a permission prompt built into the distributed installer.
