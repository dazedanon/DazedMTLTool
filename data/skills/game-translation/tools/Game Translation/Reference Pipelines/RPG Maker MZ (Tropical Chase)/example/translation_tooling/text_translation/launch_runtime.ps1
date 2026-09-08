$ErrorActionPreference = 'Stop'
$gameRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$indexPath = Join-Path $gameRoot 'index.html'
$original = [IO.File]::ReadAllBytes($indexPath)
$text = [Text.Encoding]::UTF8.GetString($original)
$needle = '<script type="text/javascript" src="js/main.js"></script>'
if (-not $text.Contains($needle)) { throw 'Unexpected index.html' }
$boot = Join-Path $PSScriptRoot 'runtime\booted.json'
if (Test-Path -LiteralPath $boot) { Move-Item -LiteralPath $boot -Destination ($boot + '.' + (Get-Date -Format 'yyyyMMddHHmmss') + '.previous') }
$profileMarker = Join-Path $PSScriptRoot 'runtime-profile'
$ownProcesses = Get-CimInstance Win32_Process -Filter "name = 'tropical-chase.exe'" | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($profileMarker) }
foreach ($gameProcess in $ownProcesses) { Stop-Process -Id $gameProcess.ProcessId -ErrorAction SilentlyContinue }
try {
    $injected = $text.Replace($needle, '<script src="translation_tooling/text_translation/runtime_host.js"></script>' + "`r`n        " + $needle)
    [IO.File]::WriteAllText($indexPath,$injected,(New-Object Text.UTF8Encoding($false)))
    $profile = Join-Path $PSScriptRoot 'runtime-profile-native'
    $gameProcess = Start-Process -FilePath (Join-Path $gameRoot 'tropical-chase.exe') -ArgumentList @('--user-data-dir="' + $profile + '"') -WorkingDirectory $gameRoot -WindowStyle Hidden -PassThru
    $deadline = (Get-Date).AddSeconds(30)
    while (-not (Test-Path -LiteralPath $boot) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }
    [PSCustomObject]@{ProcessId=$gameProcess.Id; HookLoaded=(Test-Path -LiteralPath $boot)} | ConvertTo-Json
} finally {
    [IO.File]::WriteAllBytes($indexPath,$original)
    if (-not [Linq.Enumerable]::SequenceEqual([byte[]]$original,[byte[]][IO.File]::ReadAllBytes($indexPath))) { throw 'Index restoration failed' }
}
