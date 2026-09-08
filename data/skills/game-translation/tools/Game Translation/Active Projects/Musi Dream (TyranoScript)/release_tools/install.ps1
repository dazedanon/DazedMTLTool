param(
    [Parameter(Mandatory = $true)][string]$GameRoot,
    [switch]$BuildOnly,
    [string]$Output
)
$ErrorActionPreference = 'Stop'
$patchMode = if ($BuildOnly) { 'build' } else { 'install' }
if ($Output -and -not $BuildOnly) { throw '-Output requires -BuildOnly.' }
& (Join-Path $PSScriptRoot 'invoke-patch.ps1') -Mode $patchMode -GameRoot $GameRoot -Output $Output
