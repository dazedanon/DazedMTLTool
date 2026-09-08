param(
    [string]$Csv = "",
    [string]$JsonDir = "",
    [string]$PatchDir = "",
    [string]$Id = "",
    [string]$Source = "",
    [Parameter(Mandatory = $true)]
    [string]$RuntimeSource,
    [Parameter(Mandatory = $true)]
    [string]$Translation,
    [string]$LocresKey = "",
    [string[]]$Namespace = @(),
    [string[]]$Culture = @("en", "en-US", "ja", "ja-JP", "pt", "pt-BR"),
    [string[]]$Target = @("Game", "StoryFramework"),
    [string]$NativeCulture = "ja",
    [switch]$Install
)

$ErrorActionPreference = "Stop"
$toolRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (!$Csv) { $Csv = Join-Path $toolRoot "work\translations.csv" }
if (!$JsonDir) { $JsonDir = Join-Path $toolRoot "work\json" }
if (!$PatchDir) { $PatchDir = Join-Path $toolRoot "work\patch_legacy" }
if (!(Test-Path $Csv)) { throw "Missing translation CSV at $Csv" }
if (!(Test-Path $JsonDir)) { throw "Missing JSON export directory at $JsonDir" }
if (!(Test-Path $PatchDir)) { throw "Missing patch directory at $PatchDir. Run scripts\05_apply_text_and_rebuild.ps1 first." }
if (!$Id -and !$Source -and !$LocresKey) { throw "Pass -Id, -Source, or -LocresKey." }

$py = Join-Path $toolRoot "scripts\make_locres_override.py"
$pyArgs = @(
    $py,
    "--csv", $Csv,
    "--json-dir", $JsonDir,
    "--patch-dir", $PatchDir,
    "--runtime-source", $RuntimeSource,
    "--translation", $Translation,
    "--native-culture", $NativeCulture
)
if ($Id) { $pyArgs += @("--id", $Id) }
if ($Source) { $pyArgs += @("--source", $Source) }
if ($LocresKey) { $pyArgs += @("--locres-key", $LocresKey) }
foreach ($item in $Namespace) { $pyArgs += @("--namespace", $item) }
foreach ($item in $Culture) { $pyArgs += @("--culture", $item) }
foreach ($item in $Target) { $pyArgs += @("--target", $item) }

python @pyArgs
if ($LASTEXITCODE -ne 0) { throw "Locres override generation failed with exit code $LASTEXITCODE" }

if ($Install) {
    & (Join-Path $PSScriptRoot "06_pack_patch.ps1") -Install
    if ($LASTEXITCODE -ne 0) { throw "Patch install failed with exit code $LASTEXITCODE" }
}
