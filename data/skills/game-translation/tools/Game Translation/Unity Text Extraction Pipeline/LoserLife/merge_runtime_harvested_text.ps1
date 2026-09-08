param(
    [string] $RuntimeLog = ""
)

$ErrorActionPreference = "Stop"
$Script = Join-Path $PSScriptRoot "scripts\merge_runtime_harvested_text.py"
$DefaultRuntimeLog = Join-Path (Split-Path -Parent $PSScriptRoot) "BepInEx\plugins\LoserLifeATest\runtime_harvested_texts.tsv"
$OutputsDir = Join-Path $PSScriptRoot "outputs"

if ([string]::IsNullOrWhiteSpace($RuntimeLog)) {
    $RuntimeLog = $DefaultRuntimeLog
}

$env:PYTHONIOENCODING = "utf-8"

python $Script --runtime-log $RuntimeLog --outputs-dir $OutputsDir
