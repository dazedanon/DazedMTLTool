param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$Config = (Join-Path $PSScriptRoot "..\config.json"),
    [string]$AesKey = "",
    [string]$ZenVersion = "",
    [switch]$SkipUnpack
)

$ErrorActionPreference = "Stop"
$toolRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$cfg = Get-Content -Raw -Path $Config | ConvertFrom-Json
if (!$ZenVersion) { $ZenVersion = $cfg.retocZenVersion }
$work = Join-Path $toolRoot "work"
$paksDir = Join-Path $Root $cfg.paksDir
$legacyPak = Join-Path $work "legacy_all.pak"
$extractDir = Join-Path $work "legacy_unpacked"

$retoc = Get-ChildItem -Path (Join-Path $toolRoot "tools\retoc") -Filter retoc.exe -Recurse | Select-Object -First 1
$repak = Get-ChildItem -Path (Join-Path $toolRoot "tools\repak") -Filter repak.exe -Recurse | Select-Object -First 1
if (!$retoc) { throw "retoc.exe was not found. Run scripts\01_bootstrap_tools.ps1 first." }
if (!$repak) { throw "repak.exe was not found. Run scripts\01_bootstrap_tools.ps1 first." }

$oodleDll = Get-ChildItem -Path (Join-Path $toolRoot "tools") -Filter "oo2core*_win64.dll" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if (!$oodleDll) {
    throw "This game's IoStore containers use Oodle compression. Copy a legally sourced oo2core_9_win64.dll or oo2core_5_win64.dll into .translation_tooling\tools\oodle, then rerun this script."
}
$env:PATH = "$($oodleDll.Directory.FullName);$($retoc.Directory.FullName);$($repak.Directory.FullName);$env:PATH"

New-Item -ItemType Directory -Force -Path $work | Out-Null
Remove-Item -LiteralPath $legacyPak -Force -ErrorAction SilentlyContinue

$retocArgs = @()
if ($AesKey) { $retocArgs += @("--aes-key", $AesKey) }
$retocArgs += @("to-legacy", "--version", $ZenVersion, "--no-shaders", "--no-script-objects", "--no-parallel", $paksDir, $legacyPak)

Write-Host "Converting IoStore containers to legacy pak..."
& $retoc.FullName @retocArgs
if ($LASTEXITCODE -ne 0) { throw "retoc to-legacy failed with exit code $LASTEXITCODE" }

if (!$SkipUnpack) {
    if (Test-Path $extractDir) {
        Remove-Item -LiteralPath $extractDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $extractDir | Out-Null
    Write-Host "Unpacking legacy pak. This can take a while."
    & $repak.FullName unpack -o $extractDir $legacyPak
    if ($LASTEXITCODE -ne 0) { throw "repak unpack failed with exit code $LASTEXITCODE" }
}

Write-Host "Legacy pak: $legacyPak"
if (!$SkipUnpack) { Write-Host "Unpacked assets: $extractDir" }
