@echo off
rem ============================================================================
rem  Forge_MZ installer / uninstaller  (RPG Maker MZ only)
rem  Credits: len — https://gitgud.io/zero64801/forge-mvmz (Forge plugin)
rem  Put this file and Forge_MZ.js in the GAME ROOT (next to the .exe /
rem  index.html), then double-click this file.
rem    - Not installed yet -> installs it (copies the plugin into the plugins
rem      folder and declares it at the end of plugins.js).
rem    - Already installed  -> asks whether to remove it.
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
Write-Host " Forge_MZ installer (RPG Maker MZ only)"
Write-Host "============================================"

# --- Detect MZ / locate plugins.js ------------------------------------------
$mzJs = Join-Path $root 'js\plugins.js'
if (Test-Path -LiteralPath $mzJs) {
    $pluginsJs = $mzJs; $pluginsDir = Join-Path $root 'js\plugins'
} else {
    Write-Host ""
    Write-Host "ERROR: No RPG Maker MZ game found here." -ForegroundColor Red
    Write-Host "Could not find 'js\plugins.js'."
    Write-Host "Forge is MZ-only. Place this installer and Forge_MZ.js in the"
    Write-Host "game ROOT folder (the one containing the .exe / index.html)."
    PauseExit
}
Write-Host "Detected RPG Maker MZ"
Write-Host ("plugins list: {0}" -f $pluginsJs)

$target  = Join-Path $pluginsDir 'Forge_MZ.js'
$srcRoot = Join-Path $root 'Forge_MZ.js'
$utf8    = New-Object System.Text.UTF8Encoding($false)   # no BOM
$content = [IO.File]::ReadAllText($pluginsJs)
$nl      = if ($content -match "`r`n") { "`r`n" } else { "`n" }
$declared  = [regex]::IsMatch($content, '"name"\s*:\s*"Forge_MZ"')
$fileThere = Test-Path -LiteralPath $target

# --- Already installed -> offer to remove -----------------------------------
if ($declared -or $fileThere) {
    Write-Host ""
    Write-Host "Forge_MZ is currently INSTALLED." -ForegroundColor Yellow
    $ans = Read-Host "Remove it? (Y/N)"
    if ($ans -match '^(y|yes)$') {
        if ($declared) {
            $kept = ($content -split "`r?`n") | Where-Object { $_ -notmatch '"name"\s*:\s*"Forge_MZ"' }
            $newText = ($kept -join $nl)
            $newText = [regex]::Replace($newText, ',(\s*)\];', '$1];')
            [IO.File]::WriteAllText($pluginsJs, $newText, $utf8)
            Write-Host "Removed the Forge_MZ entry from plugins.js"
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

# --- Not installed -> install -----------------------------------------------
if (-not (Test-Path -LiteralPath $srcRoot)) {
    Write-Host ""
    Write-Host "ERROR: Forge_MZ.js was not found next to this installer." -ForegroundColor Red
    Write-Host ("Expected: {0}" -f $srcRoot)
    Write-Host "Copy Forge_MZ.js into the game root and run this again."
    PauseExit
}
if (-not (Test-Path -LiteralPath $pluginsDir)) {
    New-Item -ItemType Directory -Path $pluginsDir -Force | Out-Null
}
Copy-Item -LiteralPath $srcRoot -Destination $target -Force
Write-Host ("Copied plugin -> {0}" -f $target)

$entry = '        { "name": "Forge_MZ", "status": true, "description": "Forge — in-game cheat & editor overlay", "parameters": {} }'
$idx = $content.LastIndexOf('];')
if ($idx -lt 0) {
    Write-Host ""
    Write-Host "ERROR: could not find the end of the plugin list ( ]; ) in plugins.js." -ForegroundColor Red
    Write-Host "The plugin file was copied; please add this line before the ']' yourself:"
    Write-Host $entry
    PauseExit
}
$before = $content.Substring(0, $idx).TrimEnd()
$after  = $content.Substring($idx)
$sep    = if ($before.EndsWith(',')) { $nl } else { ',' + $nl }
$newText = $before + $sep + $entry + $nl + '    ' + $after
[IO.File]::WriteAllText($pluginsJs, $newText, $utf8)
Write-Host "Declared Forge_MZ at the end of plugins.js"
Write-Host ""
Write-Host "Installed! Start the game and press F10 to open Forge." -ForegroundColor Green
PauseExit
