param(
    [string]$Config = (Join-Path $PSScriptRoot "..\config.json"),
    [string]$Csv = (Join-Path $PSScriptRoot "..\work\translations.csv"),
    [string]$JsonDir = (Join-Path $PSScriptRoot "..\work\json"),
    [string]$JsonTranslatedDir = (Join-Path $PSScriptRoot "..\work\json_translated"),
    [string]$PatchDir = (Join-Path $PSScriptRoot "..\work\patch_legacy"),
    [string]$EngineVersion = "",
    [switch]$ResizeOverflowBytecode,
    [switch]$NoResizeOverflowBytecode
)

$ErrorActionPreference = "Stop"
$toolRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$cfg = Get-Content -Raw -Path $Config | ConvertFrom-Json
if (!$EngineVersion) { $EngineVersion = $cfg.engineVersion }

$jsonDir = $JsonDir
$jsonTranslatedDir = $JsonTranslatedDir
$patchDir = $PatchDir
$py = Join-Path $toolRoot "scripts\text_json.py"
$uassetGui = Get-ChildItem -Path (Join-Path $toolRoot "tools\UAssetGUI") -Filter UAssetGUI.exe -Recurse | Select-Object -First 1
if (!$uassetGui) { throw "UAssetGUI.exe was not found. Run scripts\01_bootstrap_tools.ps1 first." }
if (!(Test-Path $Csv)) { throw "Missing translation CSV at $Csv" }
$translationRows = @(Import-Csv -Path $Csv)

$unsafeBytecodeRows = @($translationRows | Where-Object {
    $_.encoding -eq "utf16le-null" -and
    $_.translation -and
    ([System.Text.Encoding]::Unicode.GetByteCount($_.translation) -ne [System.Text.Encoding]::Unicode.GetByteCount($_.source))
})
if ($unsafeBytecodeRows.Count -gt 0) {
    if ($NoResizeOverflowBytecode) {
        Write-Host "Resize disabled; utf16le-null Kismet literals must remain byte-exact or the apply step will fail."
    } else {
        Write-Host "Encoding $($unsafeBytecodeRows.Count) utf16le-null Kismet literals as full Kismet strings and resizing changed bytecode."
    }
}

if (Test-Path $jsonTranslatedDir) { Remove-Item -LiteralPath $jsonTranslatedDir -Recurse -Force }
if (Test-Path $patchDir) { Remove-Item -LiteralPath $patchDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $jsonTranslatedDir,$patchDir | Out-Null

$applyArgs = @("apply", "--json-dir", $jsonDir, "--csv", $Csv, "--out-dir", $jsonTranslatedDir)
if ($NoResizeOverflowBytecode) {
    $applyArgs += "--no-resize-overflow-bytecode"
} else {
    $applyArgs += "--resize-overflow-bytecode"
}
python $py @applyArgs
if ($LASTEXITCODE -ne 0) { throw "Applying translations failed with exit code $LASTEXITCODE" }

$changedList = Join-Path $jsonTranslatedDir "_changed-json.txt"
if (!(Test-Path $changedList)) {
    throw "No change list was written. Make sure translation rows have non-empty translation values."
}

$rebuilt = 0
Get-Content -Path $changedList | ForEach-Object {
    $json = $_
    if (!(Test-Path $json)) { return }
    $jsonTranslatedRoot = (Resolve-Path $jsonTranslatedDir).Path
    $fullJson = (Resolve-Path $json).Path
    $rel = $fullJson.Substring($jsonTranslatedRoot.Length).TrimStart("\") -replace "\\", "/"
    if ($rel.EndsWith(".umap.json")) {
        $assetRel = $rel -replace "\.umap\.json$", ".umap"
    } else {
        $assetRel = $rel -replace "\.json$", ".uasset"
    }
    $dest = Join-Path $patchDir ($assetRel -replace "/", "\")
    New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) | Out-Null

    Write-Host "Rebuilding $assetRel"
    & $uassetGui.FullName fromjson $json $dest
    for ($i = 0; $i -lt 20 -and (!(Test-Path $dest) -or (Get-Item $dest).Length -eq 0); $i++) {
        Start-Sleep -Milliseconds 250
    }
    if (!(Test-Path $dest) -or (Get-Item $dest).Length -eq 0) {
        Start-Sleep -Milliseconds 500
        & $uassetGui.FullName fromjson $json $dest
        for ($i = 0; $i -lt 20 -and (!(Test-Path $dest) -or (Get-Item $dest).Length -eq 0); $i++) {
            Start-Sleep -Milliseconds 250
        }
    }
    if (!(Test-Path $dest) -or (Get-Item $dest).Length -eq 0) {
        throw "UAssetGUI fromjson failed for $rel with exit code $LASTEXITCODE"
    }
    $rebuilt++
}

Write-Host "Rebuilt $rebuilt translated assets under $patchDir"
