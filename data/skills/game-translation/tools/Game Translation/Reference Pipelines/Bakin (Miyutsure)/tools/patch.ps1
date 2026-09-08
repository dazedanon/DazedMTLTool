<#
Install or remove a Bakin translation overlay.

    patch.ps1 -Game <gameDir> -Dist <distDir>     # install
    patch.ps1 -Game <gameDir> -Uninstall          # revert

Install copies <distDir>\data\* into <gameDir>\data and adds the
AppDomainManager lines to bakinplayer.exe.config, keeping a .orig backup the
first time. Uninstall restores that backup and deletes what install added, so
the game is byte-for-byte back to stock. data.rbpack is never touched either way.
#>
param(
    [Parameter(Mandatory = $true)][string]$Game,
    [string]$Dist,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$data = Join-Path $Game 'data'
$cfg = Join-Path $data 'bakinplayer.exe.config'
$orig = "$cfg.orig"
$hook = 'BakinTranslationHook.dll'

if (-not (Test-Path $cfg)) { throw "not a Bakin game folder: $Game" }

if ($Uninstall) {
    Remove-Item -Recurse -Force (Join-Path $data 'translation') -ErrorAction SilentlyContinue
    Remove-Item -Force (Join-Path $data $hook) -ErrorAction SilentlyContinue
    if (Test-Path $orig) { Copy-Item $orig $cfg -Force }
    # The launcher rebuilds this on every run; stale copies confuse a later test.
    Remove-Item -Force (Join-Path $data 'bakinplayer_log.txt') -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force (Join-Path $env:TEMP 'bakin_engine_tmp') -ErrorAction SilentlyContinue
    Write-Output 'reverted to stock'
    return
}

if (-not $Dist) { throw 'install needs -Dist' }
if (-not (Test-Path $orig)) { Copy-Item $cfg $orig }

Copy-Item -Recurse -Force (Join-Path $Dist 'data\*') $data

$text = Get-Content $cfg -Raw
if ($text -notmatch 'appDomainManagerAssembly') {
    $lines = @'
    <appDomainManagerAssembly value="BakinTranslationHook, Version=0.0.0.0, Culture=neutral, PublicKeyToken=null" />
    <appDomainManagerType value="BakinTranslationHook" />
'@
    $text = $text -replace '<runtime>', "<runtime>`r`n$lines".TrimEnd()
    Set-Content -Path $cfg -Value $text -Encoding UTF8
}

$n = (Get-ChildItem -Recurse (Join-Path $data 'translation') -File | Measure-Object).Count
Write-Output "installed: $n files in data\translation, hook registered"
