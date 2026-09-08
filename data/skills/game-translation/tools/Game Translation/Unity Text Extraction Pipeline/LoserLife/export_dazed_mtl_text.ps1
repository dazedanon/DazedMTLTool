$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $PSScriptRoot "scripts\export_dazed_mtl_text.py"
$InputCsv = Join-Path $PSScriptRoot "outputs\japanese_text_all_occurrences.csv"
$OutputDir = Join-Path $PSScriptRoot "mtl_exports"

python $Script --input-csv $InputCsv --output-dir $OutputDir @args
