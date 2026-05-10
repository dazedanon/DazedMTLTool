#Requires -Version 5.1
param(
    [Parameter(Mandatory = $false)]
    [string]$GameRoot
)

$ErrorActionPreference = 'Stop'

if (-not $PSBoundParameters.ContainsKey('GameRoot') -or [string]::IsNullOrWhiteSpace($GameRoot)) {
    $GameRoot = (Get-Location).ProviderPath
}
else {
    $GameRoot = (Resolve-Path -LiteralPath $GameRoot).ProviderPath
}

$PatchBundleRoot = $PSScriptRoot

function Wait-ConsolePause {
    $null = cmd /c pause
}

function Write-BannerWrongFolder {
    Write-Host ''
    Write-Host '========================================'
    Write-Host 'ERROR: Wrong game root folder!'
    Write-Host '========================================'
    Write-Host ''
    Write-Host 'Game root cannot be the gameupdate folder itself.'
    Write-Host 'Run GameUpdate.bat from the game root (same folder as GameUpdate.bat).'
    Write-Host '========================================'
    Write-Host ''
}

function Test-WrongWorkingDirectory {
    param([string]$Root)
    return ($Root -and ((Split-Path -Leaf $Root) -ieq 'gameupdate'))
}

function Read-PatchConfig {
    param([string]$ConfigPath)
    $cfg = @{ username = ''; repo = ''; branch = '' }
    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        return $cfg
    }
    foreach ($rawLine in Get-Content -LiteralPath $ConfigPath) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith('#')) { continue }
        $eq = $line.IndexOf('=')
        if ($eq -lt 1) { continue }
        $k = $line.Substring(0, $eq).Trim().ToLowerInvariant()
        $v = if ($eq -lt $line.Length - 1) { $line.Substring($eq + 1).Trim() } else { '' }
        switch ($k) {
            'username' { $cfg.username = $v }
            'repo' { $cfg.repo = $v }
            'branch' { $cfg.branch = $v }
        }
    }
    return $cfg
}

function Invoke-SrpgUnpacker {
    param(
        [Parameter(Mandatory = $true)][string]$ExePath,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $ExePath @Arguments
        return $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}

function Invoke-SrpgPreSetup {
    param([string]$Root)
    $unpacker = Join-Path $Root 'SRPG_Unpacker.exe'
    $dts = Join-Path $Root 'data.dts'
    $dataDir = Join-Path $Root 'data'
    $projectDat = Join-Path $dataDir 'project.dat'
    $patchDir = Join-Path $Root 'patch'

    if (-not (Test-Path -LiteralPath $dts)) {
        return
    }
    if (-not (Test-Path -LiteralPath $unpacker)) {
        Write-Host '[Pre-Setup] SRPG_Unpacker.exe not found; skipping data setup.'
        return
    }

    $shouldUnpack =
        -not (Test-Path -LiteralPath $dataDir) -or
        -not (Test-Path -LiteralPath $projectDat)

    $runUnpackBlock = {
        if (Test-Path -LiteralPath $dts) {
            Write-Host '[Pre-Setup] Unpacking data.dts to data\'
            $code = Invoke-SrpgUnpacker -ExePath $unpacker -WorkingDirectory $Root -Arguments @('-o', 'data', 'data.dts')
            if ($code -ne 0) {
                Write-Host '[Pre-Setup] ERROR: Unpack failed. Continuing.'
            }
        }
        else {
            Write-Host '[Pre-Setup] Skipping unpack: data.dts missing.'
        }

        if (-not (Test-Path -LiteralPath $patchDir)) {
            if (Test-Path -LiteralPath $projectDat) {
                Write-Host '[Pre-Setup] Creating patch folder from data\project.dat'
                $code = Invoke-SrpgUnpacker -ExePath $unpacker -WorkingDirectory $Root -Arguments @('.\data\project.dat', '-c')
                if ($code -ne 0) {
                    Write-Host '[Pre-Setup] ERROR: Create Patch failed. Continuing.'
                }
            }
            else {
                Write-Host '[Pre-Setup] Skipping create patch: data\project.dat not found.'
            }
        }
    }

    if ($shouldUnpack) {
        & $runUnpackBlock
    }
    else {
        if (-not (Test-Path -LiteralPath $patchDir)) {
            if (Test-Path -LiteralPath $projectDat) {
                Write-Host '[Pre-Setup] Creating patch folder from data\project.dat'
                $code = Invoke-SrpgUnpacker -ExePath $unpacker -WorkingDirectory $Root -Arguments @('.\data\project.dat', '-c')
                if ($code -ne 0) {
                    Write-Host '[Pre-Setup] ERROR: Create Patch failed. Continuing.'
                }
            }
            else {
                Write-Host '[Pre-Setup] Skipping create patch: data\project.dat not found.'
            }
        }
    }
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

    $prevPref = $ProgressPreference
    try {
        $ProgressPreference = 'Continue'
        Invoke-WebRequest -Uri $Url -OutFile $OutFile -Headers $Headers -UseBasicParsing
    }
    finally {
        $ProgressPreference = $prevPref
    }
}

function Remove-FileOrDirectoryViaCmd {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    if (-not (Test-Path -LiteralPath $LiteralPath)) {
        return
    }
    $full = (Resolve-Path -LiteralPath $LiteralPath).ProviderPath
    $item = Get-Item -LiteralPath $LiteralPath
    if ($item.PSIsContainer) {
        cmd.exe /c "rd /s /q `"$full`"" | Out-Null
    }
    else {
        cmd.exe /c "del /f /q `"$full`"" | Out-Null
    }
}

function Remove-DownloadedRepoZip {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    Remove-FileOrDirectoryViaCmd -LiteralPath $LiteralPath
}

function Invoke-PatchDownloadExtract {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$StateFilePath,
        [Parameter(Mandatory = $true)][string]$Username,
        [Parameter(Mandatory = $true)][string]$Repo,
        [Parameter(Mandatory = $true)][string]$Branch
    )

    if ($PSVersionTable.PSEdition -ne 'Core') {
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        }
        catch {}
    }

    Set-Location -LiteralPath $Root

    $id = [uri]::EscapeDataString($Username + '/' + $Repo)
    $branchEnc = [uri]::EscapeDataString($Branch)
    $ua = 'DazedMTL-Patcher-1.0'
    $headers = @{ 'User-Agent' = $ua }
    $dlAttempts = Get-EnvInt -Name 'GAMEUPDATE_DL_ATTEMPTS' -Default 2

    $latestSha = Invoke-WithRetry -Name 'Resolve latest patch SHA' -Attempts $dlAttempts -Action {
        (Invoke-RestMethod -Uri ("https://gitgud.io/api/v4/projects/$id/repository/branches/$branchEnc") -Headers $headers).commit.id
    }
    if (-not $latestSha) { throw 'PATCH_ERR:API:Latest commit SHA response was empty.' }
    $latestSha = ([string]$latestSha).Trim()

    $previousSha = ''
    if (Test-Path -LiteralPath $StateFilePath) {
        $previousSha = (Get-Content -LiteralPath $StateFilePath -Raw).Trim()
    }
    else {
        Write-Host 'First run: comparing with remote...'
    }
    if ($previousSha -eq $latestSha) {
        return 10
    }

    Write-Host 'Downloading patch...'
    $zipPath = Join-Path $PWD.Path 'repo.zip'
    $stage = Join-Path ([IO.Path]::GetTempPath()) ('gu_' + [Guid]::NewGuid().ToString('N'))
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

    if (Test-Path -LiteralPath $stage) {
        Remove-FileOrDirectoryViaCmd -LiteralPath $stage
    }
    New-Item -ItemType Directory -Path $stage | Out-Null
    try {
        Expand-Archive -LiteralPath $zipPath -DestinationPath $stage -Force
        $dirs = @(Get-ChildItem -LiteralPath $stage -Directory)
        if ($dirs.Count -ne 1) {
            throw ('PATCH_ERR:ZIP:Expected one root folder in archive, found {0}.' -f $dirs.Count)
        }
        Copy-Item -Path (Join-Path $dirs[0].FullName '*') -Destination $PWD.Path -Recurse -Force
        Write-Host 'Removing downloaded archive (repo.zip)...'
        Remove-DownloadedRepoZip -LiteralPath $zipPath
    }
    finally {
        if (Test-Path -LiteralPath $stage) {
            Remove-FileOrDirectoryViaCmd -LiteralPath $stage
        }
    }

    Set-Content -LiteralPath $StateFilePath -Value $latestSha -Encoding Ascii
    return 0
}

function Invoke-SrpgPostApply {
    param([string]$Root)
    $unpacker = Join-Path $Root 'SRPG_Unpacker.exe'
    $dts = Join-Path $Root 'data.dts'
    $projectDat = Join-Path $Root 'data\project.dat'
    $dataDir = Join-Path $Root 'data'

    if (-not (Test-Path -LiteralPath $dts)) {
        return
    }
    if (-not (Test-Path -LiteralPath $unpacker)) {
        Write-Host 'SRPG_Unpacker.exe not found in root; skipping SRPG patch steps.'
        return
    }

    if (Test-Path -LiteralPath $projectDat) {
        Write-Host 'Applying patch to data\project.dat...'
        $code = Invoke-SrpgUnpacker -ExePath $unpacker -WorkingDirectory $Root -Arguments @('.\data\project.dat', '-a')
        if ($code -ne 0) {
            Write-Host 'ERROR: Apply Patch failed.'
        }
    }
    else {
        Write-Host 'ERROR: data\project.dat not found; cannot apply patch.'
    }

    if (Test-Path -LiteralPath $dataDir) {
        Write-Host 'Packing data folder to data.dts...'
        $code = Invoke-SrpgUnpacker -ExePath $unpacker -WorkingDirectory $Root -Arguments @('-o', 'data.dts', 'data')
        if ($code -ne 0) {
            Write-Host 'WARNING: Pack failed.'
        }
    }
    else {
        Write-Host 'Step 4: Skipping pack - data folder not found.'
    }
}

function Remove-PatchTempArtifacts {
    param([string]$Root)
    $zipPath = Join-Path $Root 'repo.zip'
    $legacyTmp = Join-Path $Root '_patch_extract_tmp'

    if (Test-Path -LiteralPath $zipPath) {
        Write-Host '  Removing repo.zip - large files can sit here for minutes if antivirus is scanning.'
        Remove-FileOrDirectoryViaCmd -LiteralPath $zipPath
    }
    if (Test-Path -LiteralPath $legacyTmp) {
        Write-Host '  Removing _patch_extract_tmp - using rd /s /q (avoids PowerShell hangs on huge folders).'
        Remove-FileOrDirectoryViaCmd -LiteralPath $legacyTmp
    }
}

try {
    if (Test-WrongWorkingDirectory -Root $GameRoot) {
        Write-BannerWrongFolder
        Wait-ConsolePause
        exit 1
    }

    Write-Host "Root: $GameRoot"

    $configPath = Join-Path $PatchBundleRoot 'patch-config.txt'
    if (-not (Test-Path -LiteralPath $configPath)) {
        Write-Host 'patch-config.txt not found next to patch.ps1 - skipping patch.'
        Wait-ConsolePause
        exit 0
    }

    $cfg = Read-PatchConfig -ConfigPath $configPath

    if ([string]::IsNullOrWhiteSpace($cfg.username)) {
        Write-Host "ERROR: 'username=' is missing in patch-config.txt"
        Wait-ConsolePause
        exit 1
    }
    if ([string]::IsNullOrWhiteSpace($cfg.repo)) {
        Write-Host "ERROR: 'repo=' is missing in patch-config.txt"
        Wait-ConsolePause
        exit 1
    }
    if ([string]::IsNullOrWhiteSpace($cfg.branch)) {
        Write-Host "ERROR: 'branch=' is missing in patch-config.txt"
        Wait-ConsolePause
        exit 1
    }

    Invoke-SrpgPreSetup -Root $GameRoot

    $stateFile = Join-Path $PatchBundleRoot 'previous_patch_sha.txt'

    $patchDlExit = 1
    try {
        $patchDlExit = Invoke-PatchDownloadExtract -Root $GameRoot -StateFilePath $stateFile `
            -Username $cfg.username -Repo $cfg.repo -Branch $cfg.branch
    }
    catch {
        Write-Host ''
        Write-Host $_.Exception.Message
        if ($_.InvocationInfo.PositionMessage) { Write-Host $_.InvocationInfo.PositionMessage }
        Remove-PatchTempArtifacts -Root $GameRoot
        Wait-ConsolePause
        exit 1
    }

    if ($patchDlExit -eq 10) {
        Write-Host 'Already up to date.'
        Wait-ConsolePause
        exit 0
    }

    if ($patchDlExit -ne 0) {
        Write-Host 'Download or extraction failed!'
        Remove-PatchTempArtifacts -Root $GameRoot
        Wait-ConsolePause
        exit 1
    }

    Write-Host 'Applying patch...'

    Invoke-SrpgPostApply -Root $GameRoot

    Write-Host 'Cleaning up...'
    Remove-PatchTempArtifacts -Root $GameRoot
    Write-Host 'Done.'

    Wait-ConsolePause
    exit 0
}
catch {
    Write-Host ''
    Write-Host $_.Exception.Message
    Wait-ConsolePause
    exit 1
}
