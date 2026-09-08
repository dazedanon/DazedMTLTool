param(
    [string] $BundleDir = "",
    [switch] $NoMerge,
    [int] $MaxWorkers = 4
)

$ErrorActionPreference = "Stop"
$Script = Join-Path $PSScriptRoot "scripts\extract_decrypted_bundle_text.py"
$DefaultBundleDir = Join-Path (Split-Path -Parent $PSScriptRoot) "BepInEx\plugins\LoserLifeATest\decrypted_bundles"
$OutputsDir = Join-Path $PSScriptRoot "outputs"

if ([string]::IsNullOrWhiteSpace($BundleDir)) {
    $BundleDir = $DefaultBundleDir
}

$env:PYTHONIOENCODING = "utf-8"

$ArgsList = @(
    $Script,
    "--bundle-dir", $BundleDir,
    "--outputs-dir", $OutputsDir,
    "--max-workers", $MaxWorkers
)

if (-not $NoMerge) {
    $ArgsList += "--merge-main"
}

python @ArgsList
