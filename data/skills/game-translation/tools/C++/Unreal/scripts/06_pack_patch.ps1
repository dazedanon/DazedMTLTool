param(
    [string]$Config = (Join-Path $PSScriptRoot "..\config.json"),
    [string]$PatchDir = (Join-Path $PSScriptRoot "..\work\patch_legacy"),
    [string]$PatchBaseName = "",
    [string]$AesKey = "",
    [string]$ZenVersion = "",
    [switch]$Install
)

$ErrorActionPreference = "Stop"
$gameRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$toolRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$cfg = Get-Content -Raw -Path $Config | ConvertFrom-Json
if (!$ZenVersion) { $ZenVersion = $cfg.retocZenVersion }
if (!$PatchBaseName) { $PatchBaseName = $cfg.patchBaseName }

$patchDir = $PatchDir
$dist = Join-Path $toolRoot "dist"
$legacyPatch = Join-Path $dist ($PatchBaseName + "_legacy.pak")
$outUtoc = Join-Path $dist ($PatchBaseName + ".utoc")
$paksDir = Join-Path $gameRoot $cfg.paksDir

$repak = Get-ChildItem -Path (Join-Path $toolRoot "tools\repak") -Filter repak.exe -Recurse | Select-Object -First 1
$retoc = Get-ChildItem -Path (Join-Path $toolRoot "tools\retoc") -Filter retoc.exe -Recurse | Select-Object -First 1
if (!$repak) { throw "repak.exe was not found. Run scripts\01_bootstrap_tools.ps1 first." }
if (!$retoc) { throw "retoc.exe was not found. Run scripts\01_bootstrap_tools.ps1 first." }
if (!(Test-Path $patchDir)) { throw "Missing patch assets at $patchDir. Run scripts\05_apply_text_and_rebuild.ps1 first." }

$oodleDll = Get-ChildItem -Path (Join-Path $toolRoot "tools") -Filter "oo2core*_win64.dll" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if (!$oodleDll) {
    throw "Patch conversion needs Oodle support. Copy a legally sourced oo2core_9_win64.dll or oo2core_5_win64.dll into .translation_tooling\tools\oodle, then rerun this script."
}
$env:PATH = "$($oodleDll.Directory.FullName);$($retoc.Directory.FullName);$($repak.Directory.FullName);$env:PATH"

New-Item -ItemType Directory -Force -Path $dist | Out-Null
Remove-Item -LiteralPath $legacyPatch,$outUtoc,($outUtoc -replace "\.utoc$", ".ucas"),($outUtoc -replace "\.utoc$", ".pak") -Force -ErrorAction SilentlyContinue

Write-Host "Packing legacy patch pak..."
& $repak.FullName pack $patchDir $legacyPatch
if ($LASTEXITCODE -ne 0) { throw "repak pack failed with exit code $LASTEXITCODE" }

$retocArgs = @()
if ($AesKey) { $retocArgs += @("--aes-key", $AesKey) }
$retocArgs += @("to-zen", $legacyPatch, $outUtoc, "--version", $ZenVersion)
Write-Host "Converting patch pak to IoStore containers..."
& $retoc.FullName @retocArgs
if ($LASTEXITCODE -ne 0) { throw "retoc to-zen failed with exit code $LASTEXITCODE" }

if ($Install) {
    Copy-Item -LiteralPath $outUtoc,($outUtoc -replace "\.utoc$", ".ucas"),($outUtoc -replace "\.utoc$", ".pak") -Destination $paksDir -Force
    Write-Host "Installed patch containers to $paksDir"
}

Write-Host "Patch files are in $dist"
