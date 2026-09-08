param(
    [Parameter(Mandatory = $true)][ValidateSet('install', 'restore', 'build')][string]$Mode,
    [Parameter(Mandatory = $true)][string]$GameRoot,
    [string]$Output
)
$ErrorActionPreference = 'Stop'
$resolvedRoot = (Resolve-Path -LiteralPath $GameRoot).ProviderPath
$gameExecutable = Join-Path $resolvedRoot 'musi_dream.exe'
if (-not (Test-Path -LiteralPath $gameExecutable -PathType Leaf)) {
    throw "musi_dream.exe was not found in $resolvedRoot"
}
if ($Mode -ne 'build') {
    $running = @(Get-Process | Where-Object {
        $_.ProcessName -eq 'musi_dream' -and ((-not $_.Path) -or [String]::Equals($_.Path, $gameExecutable, [StringComparison]::OrdinalIgnoreCase))
    })
    if ($running.Count) {
        throw "Close the game before continuing. Running process IDs: $($running.Id -join ', ')"
    }
}
$hadNodeMode = Test-Path Env:ELECTRON_RUN_AS_NODE
$previousNodeMode = $env:ELECTRON_RUN_AS_NODE
try {
    $env:ELECTRON_RUN_AS_NODE = '1'
    $patchArguments = @((Join-Path $PSScriptRoot 'patch.cjs'), '--mode', $Mode, '--game-root', $resolvedRoot, '--package-root', $PSScriptRoot)
    if ($Mode -eq 'build') {
        if (-not $Output) { throw 'Build mode requires an output file path in the game directory.' }
        $patchArguments += @('--output', [IO.Path]::GetFullPath($Output))
    }
    # The bundled executable uses the Windows GUI subsystem. A pipeline makes
    # PowerShell wait for it and populate LASTEXITCODE in Node mode.
    & $gameExecutable @patchArguments | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Patch operation failed with exit code $LASTEXITCODE. See the message above." }
} finally {
    if ($hadNodeMode) { $env:ELECTRON_RUN_AS_NODE = $previousNodeMode }
    else { Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue }
}
