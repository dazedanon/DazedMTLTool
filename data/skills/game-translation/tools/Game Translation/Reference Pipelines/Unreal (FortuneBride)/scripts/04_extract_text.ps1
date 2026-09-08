param(
    [string]$Config = (Join-Path $PSScriptRoot "..\config.json"),
    [string]$JsonDir = (Join-Path $PSScriptRoot "..\work\json"),
    [string]$OutCsv = (Join-Path $PSScriptRoot "..\work\translations.csv"),
    [string]$PlainText = (Join-Path $PSScriptRoot "..\work\plain.txt"),
    [string]$UiText = (Join-Path $PSScriptRoot "..\work\ui.txt")
)

$ErrorActionPreference = "Stop"
$toolRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$py = Join-Path $toolRoot "scripts\text_json.py"
if (!(Test-Path $JsonDir)) { throw "Missing JSON directory at $JsonDir. Run scripts\03_export_json.ps1 first." }

python $py extract --json-dir $JsonDir --out $OutCsv --plain $PlainText --ui-plain $UiText
if ($LASTEXITCODE -ne 0) { throw "Text extraction failed with exit code $LASTEXITCODE" }
Write-Host "Translation CSV: $OutCsv"
Write-Host "Plain text: $PlainText"
Write-Host "UI/other text: $UiText"
