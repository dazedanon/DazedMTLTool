param(
    [string]$Csv = "",
    [string]$Id = "",
    [string]$Source = "",
    [Parameter(Mandatory = $true)]
    [string]$Translation,
    [switch]$All,
    [switch]$Rebuild,
    [switch]$Install
)

$ErrorActionPreference = "Stop"
if (!$Csv) { $Csv = Join-Path $PSScriptRoot "..\work\translations.csv" }
if (!(Test-Path $Csv)) { throw "Missing translation CSV at $Csv" }
if (!$Id -and !$Source) { throw "Pass either -Id or -Source to select a row." }

$rows = @(Import-Csv -Path $Csv)
$matches = @($rows | Where-Object {
    (($Id -and $_.id -eq $Id) -or ($Source -and $_.source -eq $Source))
})

if ($matches.Count -eq 0) {
    throw "No matching translation rows found."
}
if ($matches.Count -gt 1 -and !$All) {
    $matches | Select-Object id,json_file,raw_offset,encoding,source | Format-Table -AutoSize
    throw "Found $($matches.Count) matches. Re-run with -Id for one row or -All to update every exact match."
}

foreach ($row in $matches) {
    $row.translation = $Translation
}

$rows | Export-Csv -NoTypeInformation -Encoding UTF8 -Path $Csv
Write-Host "Updated $($matches.Count) translation row(s) in $Csv"

if ($Rebuild -or $Install) {
    & (Join-Path $PSScriptRoot "05_apply_text_and_rebuild.ps1") -Csv $Csv
    if ($LASTEXITCODE -ne 0) { throw "Rebuild failed with exit code $LASTEXITCODE" }
}

if ($Install) {
    & (Join-Path $PSScriptRoot "06_pack_patch.ps1") -Install
    if ($LASTEXITCODE -ne 0) { throw "Patch install failed with exit code $LASTEXITCODE" }
}
