param([switch]$Offline, [switch]$SetupOnly, [switch]$Wait)
$ErrorActionPreference = 'Stop'
$applicationRoot = Split-Path -Parent $PSScriptRoot
$manifest = Get-Content -LiteralPath (Join-Path $applicationRoot 'desktop\setup-runtimes.json') -Raw | ConvertFrom-Json
# Locked image libraries ship Windows x64 wheels. ARM64 uses x64 emulation.
$architecture = 'x64'
$pythonRequest = "cpython-$($manifest.python_version)-windows-x86_64-none"
$cache = if ($env:DAZEDTL_SETUP_HOME) { $env:DAZEDTL_SETUP_HOME } else { Join-Path $env:LOCALAPPDATA 'DazedTL\setup' }
$prefix = "uv_win32_$architecture"
$url = $manifest.PSObject.Properties["${prefix}_url"].Value
$expected = $manifest.PSObject.Properties["${prefix}_sha256"].Value
if ($url -notlike 'https://*' -or $expected -notmatch '^[a-f0-9]{64}$') { throw 'The setup manifest is incomplete.' }
$uvFolder = Join-Path $cache "shell-uv-$($manifest.uv_version)-win32_$architecture"
$uv = Join-Path $uvFolder 'uv.exe'
New-Item -ItemType Directory -Path $cache -Force | Out-Null
$verified = $false
try {
    $receipt = Get-Content -LiteralPath (Join-Path $uvFolder 'verified.json') -Raw | ConvertFrom-Json
    $verified = $receipt.archive -eq $expected
} catch { }
if (-not $verified -or -not (Test-Path -LiteralPath $uv -PathType Leaf)) {
    if ($Offline) { throw 'Connect once to download the private application runtimes.' }
    $temporary = Join-Path $cache ('uv-download-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temporary | Out-Null
    try {
        Write-Host 'Downloading the verified Python setup tool...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $archive = Join-Path $temporary 'uv.zip'
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $archive
        if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
            throw 'Download verification failed; nothing was installed.'
        }
        Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $temporary 'files')
        $downloaded = @(Get-ChildItem -LiteralPath (Join-Path $temporary 'files') -Filter uv.exe -Recurse -File)
        if ($downloaded.Count -ne 1) { throw 'The runtime archive is incomplete.' }
        New-Item -ItemType Directory -Path $uvFolder -Force | Out-Null
        Copy-Item -LiteralPath $downloaded[0].FullName -Destination $uv
        ('{"archive":"' + $expected + '"}') | Set-Content -LiteralPath (Join-Path $uvFolder 'verified.json') -Encoding Ascii
    } finally {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
$env:UV_PYTHON_INSTALL_DIR = Join-Path $cache 'pythons'
$env:UV_CACHE_DIR = Join-Path $cache 'uv-cache'
$uvArguments = @('--no-config')
if ($Offline) { $uvArguments += '--offline' }
Write-Host 'Preparing a private Python runtime...'
& $uv @uvArguments python install $pythonRequest --no-bin --no-registry
if ($LASTEXITCODE -ne 0) { throw 'Python setup failed. Launch again to retry.' }
$managedPython = (& $uv @uvArguments python find --managed-python --no-project $pythonRequest | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $managedPython -PathType Leaf)) { throw 'The private Python runtime could not be located.' }
$arguments = @('-I', '-B', (Join-Path $PSScriptRoot 'setup_desktop.py'))
if ($Offline) { $arguments += '--offline' }
if ($SetupOnly) { $arguments += '--setup-only' }
if ($Wait) { $arguments += '--wait' }
& $managedPython @arguments
exit $LASTEXITCODE
