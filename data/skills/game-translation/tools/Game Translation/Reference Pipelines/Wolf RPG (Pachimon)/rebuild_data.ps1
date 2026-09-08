#!/usr/bin/env pwsh
# One-shot rebuild of the live Data folder from Data_Original + unified_translations.jsonl.
#
# Steps:
#   1. Build the unified patch JSONL from translation memory.
#   2. Inject into a fresh tree under $env:TEMP\unified_build.
#   3. Apply binary safety patches that cannot be represented as string edits.
#   4. Back up the current Data folder, then replace it with the freshly-built one.
#
# Re-run after editing build_unified_translations.py or the translation memory.
$ErrorActionPreference = "Stop"

$root = (Resolve-Path "$PSScriptRoot/../..").Path
$injectExe = Join-Path $root "_tooling/wolf_text_inject/target/release/wolf_text_inject.exe"
$exportExe = Join-Path $root "_tooling/wolf_text_export/target/release/wolf_text_export.exe"
$builder   = Join-Path $root "_tooling/mistral_translate/build_unified_translations.py"
$proxyPatch = Join-Path $root "_tooling/mistral_translate/patch_proxy_bounce_bug.py"
$jsonl     = Join-Path $root "TextExport/unified_translations.jsonl"
$build     = Join-Path $env:TEMP "unified_build"
$dataOrig  = Join-Path $root "Data_Original"
$dataLive  = Join-Path $root "Data"

if (-not (Test-Path $injectExe)) { throw "missing inject exe at $injectExe" }
if (-not (Test-Path $exportExe)) { throw "missing export exe at $exportExe" }
if (-not (Test-Path $proxyPatch)) { throw "missing proxy bounce patch at $proxyPatch" }
if (-not (Test-Path $dataOrig))  { throw "missing Data_Original at $dataOrig" }

$scanCe = Join-Path $root "TextExport_original_db_command_scan/extra_scan_ce.csv"
$scanner = Join-Path $root "_tooling/mistral_translate/scan_extra_command_strings.py"
if (-not (Test-Path $scanCe)) {
    Write-Host "[0/5] Generating extra command-scan CSV (CID 102/122/150 in CommonEvent.dat)..."
    & py $scanner $dataOrig "-o" $scanCe
    if ($LASTEXITCODE -ne 0) { throw "extra scanner failed" }
}

Write-Host "[1/5] Building unified translation JSONL..."
& py $builder
if ($LASTEXITCODE -ne 0) { throw "builder failed" }

if (Test-Path $build) { Remove-Item -Recurse -Force $build }
Write-Host "[2/5] Injecting translations into $build..."
& $injectExe $dataOrig $jsonl $build --asset-root $dataOrig
if ($LASTEXITCODE -ne 0) { throw "inject failed" }

Write-Host "[3/5] Applying CommonEvent zero-key safety patch..."
& py $proxyPatch --data-root $build
if ($LASTEXITCODE -ne 0) { throw "proxy bounce patch failed" }

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = Join-Path $root "Data_pre_unified_$ts"
Write-Host "[4/5] Backing up current Data -> $backup..."
if (Test-Path $dataLive) {
    Move-Item -Path $dataLive -Destination $backup
}

Write-Host "[5/5] Copying built tree to Data..."
Copy-Item -Recurse -Force $build $dataLive

Write-Host ""
Write-Host "Done. Live Data refreshed."
Write-Host "Backup: $backup"
