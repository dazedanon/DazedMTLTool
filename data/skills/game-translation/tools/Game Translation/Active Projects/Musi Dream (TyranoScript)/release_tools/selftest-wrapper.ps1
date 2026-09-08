param([Parameter(Mandatory = $true)][string]$FixtureRoot)
$ErrorActionPreference = 'Stop'
foreach ($scriptName in @('install.ps1', 'restore.ps1', 'invoke-patch.ps1', 'patch.cjs')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $scriptName) -Destination (Join-Path (Join-Path $FixtureRoot 'package') $scriptName)
}
$savedNodeSetting = $env:ELECTRON_RUN_AS_NODE
try {
    $env:ELECTRON_RUN_AS_NODE = 'selftest-sentinel'
    & (Join-Path $FixtureRoot 'package\install.ps1') -GameRoot (Join-Path $FixtureRoot 'game') -BuildOnly -Output (Join-Path $FixtureRoot 'game\wrapper.asar')
    if ($env:ELECTRON_RUN_AS_NODE -ne 'selftest-sentinel') { throw 'Node-mode environment was not restored after success' }
    $caught = $false
    try {
        & (Join-Path $FixtureRoot 'package\install.ps1') -GameRoot (Join-Path $FixtureRoot 'game') -BuildOnly -Output (Join-Path $FixtureRoot 'game\wrapper.asar')
    } catch { $caught = $true }
    if (-not $caught) { throw 'Wrapper failed to report a native nonzero exit code' }
    if ($env:ELECTRON_RUN_AS_NODE -ne 'selftest-sentinel') { throw 'Node-mode environment was not restored after failure' }
    Write-Output 'WRAPPER_SUCCESS_FAILURE_AND_ENV_RESTORATION_PASSED'
} finally {
    if ($null -eq $savedNodeSetting) { Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue }
    else { $env:ELECTRON_RUN_AS_NODE = $savedNodeSetting }
}
