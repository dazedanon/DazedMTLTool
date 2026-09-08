$ErrorActionPreference = 'Stop'
$qaGameRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../test_game')).Path
$qaHadNode = Test-Path Env:ELECTRON_RUN_AS_NODE
$qaNodeMode = $env:ELECTRON_RUN_AS_NODE
try {
    Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
    $qaUserData = Join-Path $qaGameRoot 'qa-user-data'
    Start-Process -FilePath (Join-Path $qaGameRoot 'musi_dream.exe') -WorkingDirectory $qaGameRoot -WindowStyle Hidden -ArgumentList @('--remote-debugging-port=9222', '--remote-debugging-address=127.0.0.1', ('--user-data-dir="' + $qaUserData + '"')) -PassThru | Select-Object Id,Path
} finally {
    if ($qaHadNode) { $env:ELECTRON_RUN_AS_NODE = $qaNodeMode }
    else { Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue }
}
