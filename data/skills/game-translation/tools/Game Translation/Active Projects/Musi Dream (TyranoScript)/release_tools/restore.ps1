param([Parameter(Mandatory = $true)][string]$GameRoot)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'invoke-patch.ps1') -Mode restore -GameRoot $GameRoot
