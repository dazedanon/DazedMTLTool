@echo off
rem ============================================================================
rem  Forge_MV installer / uninstaller  (RPG Maker MV only)
rem  Credits: len — https://gitgud.io/zero64801/forge-mvmz (Forge plugin)
rem  Put this file and Forge_MV.js in the GAME ROOT (next to the .exe /
rem  index.html), then double-click this file.
rem ============================================================================
chcp 65001 >nul
setlocal
set "FORGE_ROOT=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$l=Get-Content -LiteralPath '%~f0'; $i=[Array]::IndexOf($l,'#:PSSTART'); Invoke-Expression (($l[($i+1)..($l.Count-1)]) -join [char]10)"
endlocal
exit /b
#:PSSTART
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
function PauseExit { [void](Read-Host "`nPress Enter to exit"); exit }

$root = $env:FORGE_ROOT
Write-Host "============================================"
Write-Host " Forge_MV installer (RPG Maker MV only)"
Write-Host "============================================"

$mvJs = Join-Path $root 'www\js\plugins.js'
if (Test-Path -LiteralPath $mvJs) {
    $pluginsJs = $mvJs; $pluginsDir = Join-Path $root 'www\js\plugins'
} else {
    Write-Host ""
    Write-Host "ERROR: No RPG Maker MV game found here." -ForegroundColor Red
    Write-Host "Could not find 'www\js\plugins.js'."
    Write-Host "Place this installer and Forge_MV.js in the game ROOT folder."
    PauseExit
}
Write-Host "Detected RPG Maker MV"
Write-Host ("plugins list: {0}" -f $pluginsJs)

$target  = Join-Path $pluginsDir 'Forge_MV.js'
$srcRoot = Join-Path $root 'Forge_MV.js'
$utf8    = New-Object System.Text.UTF8Encoding($false)
$content = [IO.File]::ReadAllText($pluginsJs)
$nl      = if ($content -match "`r`n") { "`r`n" } else { "`n" }
$declared  = [regex]::IsMatch($content, '"name"\s*:\s*"Forge_MV"')
$fileThere = Test-Path -LiteralPath $target

if ($declared -or $fileThere) {
    Write-Host ""
    Write-Host "Forge_MV is currently INSTALLED." -ForegroundColor Yellow
    $ans = Read-Host "Remove it? (Y/N)"
    if ($ans -match '^(y|yes)$') {
        if ($declared) {
            $kept = ($content -split "`r?`n") | Where-Object { $_ -notmatch '"name"\s*:\s*"Forge_MV"' }
            $newText = ($kept -join $nl)
            $newText = [regex]::Replace($newText, ',(\s*)\];', '$1];')
            [IO.File]::WriteAllText($pluginsJs, $newText, $utf8)
            Write-Host "Removed the Forge_MV entry from plugins.js"
        }
        if ($fileThere) {
            Remove-Item -LiteralPath $target -Force
            Write-Host ("Deleted {0}" -f $target)
        }
        Write-Host ""
        Write-Host "Uninstalled." -ForegroundColor Green
    } else {
        Write-Host "Cancelled - nothing changed."
    }
    PauseExit
}

if (-not (Test-Path -LiteralPath $srcRoot)) {
    Write-Host ""
    Write-Host "ERROR: Forge_MV.js was not found next to this installer." -ForegroundColor Red
    Write-Host ("Expected: {0}" -f $srcRoot)
    PauseExit
}
if (-not (Test-Path -LiteralPath $pluginsDir)) {
    New-Item -ItemType Directory -Path $pluginsDir -Force | Out-Null
}
Copy-Item -LiteralPath $srcRoot -Destination $target -Force
Write-Host ("Copied plugin -> {0}" -f $target)

$entry = '        { "name": "Forge_MV", "status": true, "description": "Forge — in-game cheat & editor overlay", "parameters": {} }'
$idx = $content.LastIndexOf('];')
if ($idx -lt 0) {
    Write-Host ""
    Write-Host "ERROR: could not find the end of the plugin list ( ]; ) in plugins.js." -ForegroundColor Red
    PauseExit
}
$before = $content.Substring(0, $idx).TrimEnd()
$after  = $content.Substring($idx)
$sep    = if ($before.EndsWith(',')) { $nl } else { ',' + $nl }
$newText = $before + $sep + $entry + $nl + '    ' + $after
[IO.File]::WriteAllText($pluginsJs, $newText, $utf8)
Write-Host "Declared Forge_MV at the end of plugins.js"
Write-Host ""
Write-Host "Installed! Start the game and press F10 to open Forge." -ForegroundColor Green
PauseExit
