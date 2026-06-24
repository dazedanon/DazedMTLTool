@echo off
rem ============================================================================
rem  TLInspector installer / uninstaller  (RPG Maker MV & MZ)
rem  Idea by Sakura · Plugin by Kao_SSS
rem  Put this file and TLInspector.js in the GAME ROOT (next to the .exe /
rem  index.html), then double-click this file.
rem    - Not installed yet -> installs it (moves the plugin into the plugins
rem      folder and declares it at the end of plugins.js).
rem    - Already installed  -> asks whether to remove it.
rem ============================================================================
chcp 65001 >nul
setlocal
set "TLI_ROOT=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$l=Get-Content -LiteralPath '%~f0'; $i=[Array]::IndexOf($l,'#:PSSTART'); Invoke-Expression (($l[($i+1)..($l.Count-1)]) -join [char]10)"
endlocal
exit /b
#:PSSTART
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
function PauseExit { [void](Read-Host "`nPress Enter to exit"); exit }

$root = $env:TLI_ROOT
Write-Host "============================================"
Write-Host " TLInspector installer"
Write-Host " Idea by Sakura · Plugin by Kao_SSS"
Write-Host "============================================"

# --- Detect engine / locate plugins.js (MV uses www\, MZ does not) ----------
$mvJs = Join-Path $root 'www\js\plugins.js'
$mzJs = Join-Path $root 'js\plugins.js'
if (Test-Path -LiteralPath $mvJs) {
    $engine = 'MV'; $pluginsJs = $mvJs; $pluginsDir = Join-Path $root 'www\js\plugins'
} elseif (Test-Path -LiteralPath $mzJs) {
    $engine = 'MZ'; $pluginsJs = $mzJs; $pluginsDir = Join-Path $root 'js\plugins'
} else {
    Write-Host ""
    Write-Host "ERROR: No RPG Maker MV/MZ game found here." -ForegroundColor Red
    Write-Host "Could not find 'www\js\plugins.js' (MV) or 'js\plugins.js' (MZ)."
    Write-Host "Place this installer and TLInspector.js in the game ROOT folder"
    Write-Host "(the one containing the .exe / index.html) and run it again."
    PauseExit
}
Write-Host ("Detected RPG Maker {0}" -f $engine)
Write-Host ("plugins list: {0}" -f $pluginsJs)

$target  = Join-Path $pluginsDir 'TLInspector.js'
$srcRoot = Join-Path $root 'TLInspector.js'
$utf8    = New-Object System.Text.UTF8Encoding($false)   # no BOM
$content = [IO.File]::ReadAllText($pluginsJs)
$nl      = if ($content -match "`r`n") { "`r`n" } else { "`n" }
$declared  = [regex]::IsMatch($content, '"name"\s*:\s*"TLInspector"')
$hasRemnants = [regex]::IsMatch($content, '"description"\s*:\s*"TL source inspector"')
$fileThere = Test-Path -LiteralPath $target

# --- Already installed -> offer to remove -----------------------------------
if ($declared -or $hasRemnants -or $fileThere) {
    Write-Host ""
    Write-Host "TLInspector is currently INSTALLED." -ForegroundColor Yellow
    $ans = Read-Host "Remove it? (Y/N)"
    if ($ans -match '^(y|yes)$') {
        if ($declared -or $hasRemnants) {
            $newText = $content
            while ($true) {
                $m = [regex]::Match($newText, '"name"\s*:\s*"TLInspector"')
                if (-not $m.Success) { break }
                $start = $newText.LastIndexOf('{', $m.Index)
                if ($start -lt 0) { break }
                $depth = 0
                $end = -1
                for ($i = $start; $i -lt $newText.Length; $i++) {
                    if ($newText[$i] -eq '{') { $depth++ }
                    elseif ($newText[$i] -eq '}') {
                        $depth--
                        if ($depth -eq 0) { $end = $i + 1; break }
                    }
                }
                if ($end -lt 0) { break }
                while ($end -lt $newText.Length -and $newText[$end] -match '\s') { $end++ }
                if ($end -lt $newText.Length -and $newText[$end] -eq ',') { $end++ }
                $before = $newText.Substring(0, $start).TrimEnd()
                $after = $newText.Substring($end).TrimStart()
                if ($before.EndsWith(',')) { $before = $before.Substring(0, $before.Length - 1).TrimEnd() }
                elseif ($after.StartsWith(',')) { $after = $after.Substring(1).TrimStart() }
                $newText = $before + $after
            }
            $newText = [regex]::Replace($newText, ',\s*\{\s*"status"\s*:\s*true\s*,\s*"description"\s*:\s*"TL source inspector"\s*,\s*"parameters"\s*:\s*\{[^{}]*\}\s*\}', '')
            $newText = [regex]::Replace($newText, '\{\s*"status"\s*:\s*true\s*,\s*"description"\s*:\s*"TL source inspector"\s*,\s*"parameters"\s*:\s*\{[^{}]*\}\s*\}\s*,?', '')
            $newText = [regex]::Replace($newText, ',(\s*)\];', '$1];')
            [IO.File]::WriteAllText($pluginsJs, $newText, $utf8)
            Write-Host "Removed the TLInspector entry from plugins.js"
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
    Write-Host "ERROR: TLInspector.js was not found next to this installer." -ForegroundColor Red
    Write-Host ("Expected: {0}" -f $srcRoot)
    Write-Host "Copy TLInspector.js into the game root and run this again."
    PauseExit
}
if (-not (Test-Path -LiteralPath $pluginsDir)) {
    New-Item -ItemType Directory -Path $pluginsDir -Force | Out-Null
}
Move-Item -LiteralPath $srcRoot -Destination $target -Force
Write-Host ("Moved plugin -> {0}" -f $target)

# Insert the declaration as the last entry, just before the closing  ];
$entry = '        { "name": "TLInspector", "status": true, "description": "TL source inspector", "parameters": {} }'
$idx = $content.LastIndexOf('];')
if ($idx -lt 0) {
    Write-Host ""
    Write-Host "ERROR: could not find the end of the plugin list ( ]; ) in plugins.js." -ForegroundColor Red
    Write-Host "The plugin file was moved; please add this line before the ']' yourself:"
    Write-Host $entry
    PauseExit
}
$before = $content.Substring(0, $idx).TrimEnd()
$after  = $content.Substring($idx)                 # starts at  ];
$sep    = if ($before.EndsWith(',')) { $nl } else { ',' + $nl }
$newText = $before + $sep + $entry + $nl + '    ' + $after
[IO.File]::WriteAllText($pluginsJs, $newText, $utf8)
Write-Host "Declared TLInspector at the end of plugins.js"
Write-Host ""
Write-Host "Installed! Start the game, press F10 to open the inspector, and use edit to save text changes in-game." -ForegroundColor Green
PauseExit
