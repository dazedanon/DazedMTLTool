$ErrorActionPreference = 'Stop'
$toolRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$coldRoot = (Resolve-Path (Join-Path $toolRoot 'clean_game')).Path
$coldExe = Join-Path $coldRoot 'tropical-chase.exe'
$profile = Join-Path $PSScriptRoot 'cold-profile'
$reports = Join-Path $PSScriptRoot 'reports'
[void][IO.Directory]::CreateDirectory($reports)
$index = [IO.File]::ReadAllText((Join-Path $coldRoot 'index.html'))
$expectedTitle = (Get-Content -LiteralPath (Join-Path $coldRoot 'data/System.json') -Encoding UTF8 -Raw | ConvertFrom-Json).gameTitle
if ($index.Contains('translation_tooling') -or $index.Contains('runtime_host')) { throw 'QA startup hook present' }
$existing = Get-CimInstance Win32_Process -Filter "name = 'tropical-chase.exe'" | Where-Object { $_.ExecutablePath -eq $coldExe }
if ($existing) { throw 'The isolated game copy is already running' }
try {
    $launched = Start-Process -FilePath $coldExe -ArgumentList @('--user-data-dir="' + $profile + '"') -WorkingDirectory $coldRoot -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 18
    $owned = Get-CimInstance Win32_Process -Filter "name = 'tropical-chase.exe'" | Where-Object { $_.ExecutablePath -eq $coldExe }
    $windowProcess = $owned | ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue } | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
    if (-not $windowProcess) { throw 'No native game window' }
    $shot = Join-Path $reports 'cold_boot.png'
    & python -B -X utf8 (Join-Path $toolRoot 'text_translation/capture_window.py') $windowProcess.MainWindowHandle.ToInt64() $shot
    if ($LASTEXITCODE -ne 0) { throw 'Native window capture failed' }
    $result = [PSCustomObject]@{WindowTitle=$windowProcess.MainWindowTitle; ExpectedTitle=$expectedTitle; Responding=$windowProcess.Responding; HarnessLoaded=$false; Screenshot='reports/cold_boot.png'; Pass=($windowProcess.MainWindowTitle -eq $expectedTitle -and $windowProcess.Responding)}
    $result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reports 'cold_boot.json') -Encoding UTF8
    $result | ConvertTo-Json
} finally {
    $owned = Get-CimInstance Win32_Process -Filter "name = 'tropical-chase.exe'" | Where-Object { $_.ExecutablePath -eq $coldExe }
    foreach ($ownedProcess in $owned) { Stop-Process -Id $ownedProcess.ProcessId -ErrorAction SilentlyContinue }
}
