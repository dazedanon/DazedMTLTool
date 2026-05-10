#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)]
    [string]$GameRoot,
    [Parameter(Mandatory = $true)]
    [string]$StateFile
)

$ErrorActionPreference = 'Stop'
$exitCode = 1

if ($PSVersionTable.PSEdition -ne 'Core') {
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    }
    catch {}
}

function Get-EnvInt {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$Default
    )
    $raw = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($raw)) { return $Default }
    $parsed = 0
    if ([int]::TryParse([string]$raw, [ref]$parsed) -and $parsed -gt 0) { return $parsed }
    return $Default
}

function Invoke-WithRetry {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [Parameter(Mandatory = $true)][string]$Name,
        [int]$Attempts = 2,
        [int]$DelaySeconds = 2
    )
    $lastErr = $null
    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            return & $Action
        }
        catch {
            $lastErr = $_
            if ($i -lt $Attempts) {
                Write-Host ("{0} failed ({1}/{2}), retrying..." -f $Name, $i, $Attempts)
                Start-Sleep -Seconds $DelaySeconds
            }
        }
    }
    throw $lastErr
}

function Download-WithIwrSpeedProgress {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$OutFile,
        [Parameter(Mandatory = $true)][hashtable]$Headers
    )

    if (Test-Path -LiteralPath $OutFile) {
        Remove-Item -LiteralPath $OutFile -Force
    }

    # Fast path: let Invoke-WebRequest handle transfer and progress internally.
    # Custom stream/polling progress gives richer stats but adds measurable overhead.
    $prevPref = $ProgressPreference
    try {
        $ProgressPreference = 'Continue'
        Invoke-WebRequest -Uri $Url -OutFile $OutFile -Headers $Headers -UseBasicParsing
    }
    finally {
        $ProgressPreference = $prevPref
    }
}

try {
    Set-Location -LiteralPath $GameRoot

    if (-not $env:GU_USERNAME -or -not $env:GU_REPO -or -not $env:GU_BRANCH) {
        throw 'PATCH_ERR:CONFIG:patch.bat must set GU_USERNAME, GU_REPO, and GU_BRANCH.'
    }

    $id = [uri]::EscapeDataString($env:GU_USERNAME + '/' + $env:GU_REPO)
    $branch = [uri]::EscapeDataString($env:GU_BRANCH)
    $ua = 'DazedMTL-Patcher-1.0'
    $headers = @{ 'User-Agent' = $ua }
    $dlAttempts = Get-EnvInt -Name 'GAMEUPDATE_DL_ATTEMPTS' -Default 2

    $latestSha = Invoke-WithRetry -Name 'Resolve latest patch SHA' -Attempts $dlAttempts -Action {
        (Invoke-RestMethod -Uri ("https://gitgud.io/api/v4/projects/$id/repository/branches/$branch") -Headers $headers).commit.id
    }
    if (-not $latestSha) { throw 'PATCH_ERR:API:Latest commit SHA response was empty.' }
    $latestSha = ([string]$latestSha).Trim()

    $previousSha = ''
    if (Test-Path -LiteralPath $StateFile) {
        $previousSha = (Get-Content -LiteralPath $StateFile -Raw).Trim()
    } else {
        Write-Host 'No saved patch version yet (first run); comparing with remote...'
    }
    if ($previousSha -eq $latestSha) {
        Write-Host 'Already up to date (matches latest patch commit).'
        exit 10
    }

    Write-Host 'Update found! Patching...'
    Write-Host 'Downloading latest patch... (backend: iwr, GitLab API)'
    $zipPath = Join-Path $PWD.Path 'repo.zip'
    # Use a short temp extract root to avoid Windows MAX_PATH issues when
    # GitLab archive root folder includes long commit SHA suffixes.
    $stage = Join-Path ([IO.Path]::GetTempPath()) ("gu_" + [Guid]::NewGuid().ToString("N"))
    $archiveSha = [uri]::EscapeDataString($latestSha)
    $archiveUrl = "https://gitgud.io/api/v4/projects/$id/repository/archive.zip?sha=$archiveSha"

    $dlSw = [System.Diagnostics.Stopwatch]::StartNew()
    Invoke-WithRetry -Name 'Download archive with Invoke-WebRequest' -Attempts $dlAttempts -Action {
        Download-WithIwrSpeedProgress -Url $archiveUrl -OutFile $zipPath -Headers $headers
    } | Out-Null
    $dlSw.Stop()
    $bytes = (Get-Item -LiteralPath $zipPath).Length
    $secs = [Math]::Max($dlSw.Elapsed.TotalSeconds, 0.001)
    $mbps = ($bytes / 1MB) / $secs
    Write-Host ("Download complete via iwr: {0:N1} MB in {1:N1}s ({2:N1} MB/s)" -f ($bytes / 1MB), $secs, $mbps)

    $fs = [System.IO.File]::OpenRead($zipPath)
    try {
        $hdr = New-Object byte[] 4
        if ($fs.Read($hdr, 0, 4) -lt 4 -or $hdr[0] -ne 0x50 -or $hdr[1] -ne 0x4B) {
            throw 'PATCH_ERR:ZIP:Download is not a valid ZIP (error page or empty file).'
        }
    }
    finally {
        $fs.Dispose()
    }

    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    New-Item -ItemType Directory -Path $stage | Out-Null
    try {
        Expand-Archive -LiteralPath $zipPath -DestinationPath $stage -Force
        $dirs = @(Get-ChildItem -LiteralPath $stage -Directory)
        if ($dirs.Count -ne 1) {
            throw ('PATCH_ERR:ZIP:Expected one root folder in archive, found {0}.' -f $dirs.Count)
        }
        Copy-Item -Path (Join-Path $dirs[0].FullName '*') -Destination $PWD.Path -Recurse -Force
    }
    finally {
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    }

    Set-Content -LiteralPath $StateFile -Value $latestSha -Encoding Ascii
    $exitCode = 0
}
catch {
    Write-Host ''
    Write-Host ($_.Exception.Message)
    if ($_.InvocationInfo.PositionMessage) { Write-Host $_.InvocationInfo.PositionMessage }
    $exitCode = 1
}

exit $exitCode
