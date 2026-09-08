param(
    [string]$Config = (Join-Path $PSScriptRoot "..\config.json"),
    [string]$ExtractedDir = (Join-Path $PSScriptRoot "..\work\legacy_unpacked"),
    [string]$EngineVersion = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$toolRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$cfg = Get-Content -Raw -Path $Config | ConvertFrom-Json
if (!$EngineVersion) { $EngineVersion = $cfg.engineVersion }

$uassetGui = Get-ChildItem -Path (Join-Path $toolRoot "tools\UAssetGUI") -Filter UAssetGUI.exe -Recurse | Select-Object -First 1
if (!$uassetGui) { throw "UAssetGUI.exe was not found. Run scripts\01_bootstrap_tools.ps1 first." }

$targets = Join-Path $toolRoot "work\candidate-assets.txt"
if (!(Test-Path $targets)) { throw "Missing candidate list. Run scripts\00_inventory.ps1 first." }
if (!(Test-Path $ExtractedDir)) { throw "Missing extracted assets at $ExtractedDir. Run scripts\02_extract_legacy.ps1 first." }

$jsonRoot = Join-Path $toolRoot "work\json"
New-Item -ItemType Directory -Force -Path $jsonRoot | Out-Null

$count = 0
$failures = @()
$targetAssets = Get-Content -Path $targets
foreach ($targetAsset in $targetAssets) {
    $rel = ($targetAsset -replace "\\", "/")
    $source = Join-Path $ExtractedDir ($rel -replace "/", "\")
    if (!(Test-Path $source)) {
        Write-Warning "Missing extracted asset: $rel"
        $failures += $rel
        continue
    }

    if ($rel.EndsWith(".umap")) {
        $jsonRel = ($rel -replace "\.umap$", ".umap.json")
    } else {
        $jsonRel = ($rel -replace "\.uasset$", ".json")
    }
    $dest = Join-Path $jsonRoot ($jsonRel -replace "/", "\")
    if ((Test-Path $dest) -and !$Force) {
        continue
    }

    New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) | Out-Null
    Write-Host "Exporting $rel"
    & $uassetGui.FullName tojson $source $dest $EngineVersion
    for ($i = 0; $i -lt 20 -and (!(Test-Path $dest) -or (Get-Item $dest).Length -eq 0); $i++) {
        Start-Sleep -Milliseconds 250
    }
    if (!(Test-Path $dest) -or (Get-Item $dest).Length -eq 0) {
        Start-Sleep -Milliseconds 500
        & $uassetGui.FullName tojson $source $dest $EngineVersion
        for ($i = 0; $i -lt 20 -and (!(Test-Path $dest) -or (Get-Item $dest).Length -eq 0); $i++) {
            Start-Sleep -Milliseconds 250
        }
    }
    if (!(Test-Path $dest) -or (Get-Item $dest).Length -eq 0) {
        Write-Warning "UAssetGUI tojson failed for $rel"
        $failures += $rel
        continue
    }
    $count++
}

$failurePath = Join-Path $toolRoot "work\json-export-failures.txt"
if ($failures.Count -gt 0) {
    $failures | Set-Content -Encoding UTF8 -Path $failurePath
    Write-Warning "Export failed for $($failures.Count) assets. See $failurePath"
} else {
    Remove-Item -LiteralPath $failurePath -Force -ErrorAction SilentlyContinue
}
Write-Host "Exported $count JSON assets to $jsonRoot"
