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
    Write-Host ''
    Write-Host 'Press any key to close this window...'
    try {
        $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
    }
    catch {
        Read-Host 'Press Enter to close'
    }
}

function Get-DazedPatcherBannerGlyphs {
    return @{
        'A' = @('        ', '  AAA   ', ' A   A  ', ' AAAAA  ', ' A   A  ', ' A   A  ', '        ')
        'C' = @('        ', '  CCCC  ', ' C      ', ' C      ', ' C      ', '  CCCC  ', '        ')
        'D' = @('        ', ' DDDDD  ', ' D    D ', ' D    D ', ' D    D ', ' DDDDD  ', '        ')
        'E' = @('        ', ' EEEEE  ', ' E      ', ' EEE    ', ' E      ', ' EEEEE  ', '        ')
        'H' = @('        ', ' H   H  ', ' H   H  ', ' HHHHH  ', ' H   H  ', ' H   H  ', '        ')
        'P' = @('        ', ' PPPPP  ', ' P   P  ', ' PPPP   ', ' P      ', ' P      ', '        ')
        'R' = @('        ', ' RRRRR  ', ' R   R  ', ' RRRR   ', ' R  R   ', ' R   R  ', '        ')
        'T' = @('        ', ' TTTTT  ', '   T    ', '   T    ', '   T    ', '   T    ', '        ')
        'Z' = @('        ', ' ZZZZZ  ', '    Z   ', '   Z    ', '  Z     ', ' ZZZZZ  ', '        ')
    }
}

function Build-AsciiWordLines {
    param(
        [Parameter(Mandatory = $true)][string]$Word,
        [hashtable]$Glyphs
    )
    $letters = @(
        $Word.ToUpperInvariant().ToCharArray() | ForEach-Object { [string]$_ }
    )
    $rows = New-Object string[] 7
    for ($r = 0; $r -lt 7; $r++) {
        $parts = New-Object System.Collections.Generic.List[string]
        foreach ($letter in $letters) {
            if (-not $Glyphs.ContainsKey($letter)) {
                throw "Banner glyph missing for '$letter'."
            }
            $parts.Add($Glyphs[$letter][$r])
        }
        $rows[$r] = ($parts -join ' ')
    }
    return [string[]]$rows
}

function ConvertTo-LineStringArray {
    param([AllowNull()][object]$Value)
    if ($null -eq $Value) { return @() }
    if ($Value -is [string[]]) { return $Value }
    if ($Value -is [System.Collections.Generic.List[string]]) { return $Value.ToArray() }
    if ($Value -is [string]) {
        if ([string]::IsNullOrWhiteSpace([string]$Value)) { return @() }
        return ,[string]$Value
    }
    return [string[]](@($Value) | ForEach-Object { if ($null -eq $_) { '' } else { "$_" } })
}

function Pad-LineBlockToHeight {
    param(
        [Parameter(Mandatory = $true, Position = 0)][object]$Rows,
        [Parameter(Mandatory = $true, Position = 1)][int]$TargetHeight
    )
    [string[]]$lines = ConvertTo-LineStringArray -Value $Rows
    if ($lines.Count -eq 0 -and $TargetHeight -gt 0) {
        $blank = New-Object string[] $TargetHeight
        for ($i = 0; $i -lt $TargetHeight; $i++) { $blank[$i] = '' }
        return $blank
    }
    if ($lines.Count -ge $TargetHeight) {
        return [string[]]$lines
    }
    $padTotal = $TargetHeight - $lines.Count
    $padTop = [int][Math]::Floor($padTotal / 2)
    $padBot = $padTotal - $padTop
    $top = @()
    for ($i = 0; $i -lt $padTop; $i++) { $top += '' }
    $bot = @()
    for ($i = 0; $i -lt $padBot; $i++) { $bot += '' }
    return [string[]]($top + $lines + $bot)
}

function Get-EmbeddedIconAsciiCatLines {
    # Refresh via generate_icon_ascii.ps1 when assets/icon.png changes.
    $raw = @'
       #            %#
     %:.-@         #..=
   #:.-*:.:#     *..=*..-%
    *=.:.+#  %%  @*-:::+#
      *-#   +...=#  =-%
    %      #..==..:#                  %@
  %..*     -.:%%#=..=##*##%%     %*=:...+
*:.=+.:=   ..=%##%*:..::.....:=+:..-=*:.:
*=:--.=*   ..=%###%########*+=:.-+#%%%:.-
   -:%    #..=%###%%%%%###%%%%%#%%%#%*..+
         %..=%##-.=*=-*%#####%%%%%#%#:.:
         +.:###%+....:*%###:.=*=-*%%-..%
         -.:%#%+..:..=%####=....-#%%+..%
         *..*%##**%*-=###%=..:..=%#%*..#
          =..*%%%%#%%%#####*#%*-+%%%-..
           +..-*#%%%%######%%#%%%%*:..#
            %+...-+*##%%%%%%%%#*+-..=%
             %..:.....::---::....:*%
             :.:%%#*+=--::::-=+:.:*
            %..+%#%%%%%%%%%%%%%%+..-@    #-:::+@
            #..+%###############%#:.:%  #..=*:..#
             ..=%################%#:..% %..+%%-..@
            %..:%###%#%##%%#%#####%#:.-  *..*%*..+
           #....*%##-.+%%#:.+%##%#%%*..*  :.-%%:.-
          %..=..-%#%:..#%+..+%#%+::#%:.-  :.-%%:.-
          -.:%=..*%%*..+%:.:%#%#..:#%=.. #..+%*..+
          ..=%#..:%%#..-#..=%#%-..*%%=..*:.-%%-..@
          -.-%%+..+%%-.:+..+%%+..+%#%-....=%%-..#
          +..*%*..:%%=..=..*%%:..*%%#...=#%+:.:#
          ..-**..:+**=..:..+**+:..**+..=*=:..+
          +..............................:=#
            %%%%%%%%%%%%%%%%%%%%%%%%%%%%@
'@
    return [string[]]@($raw -split '\r?\n')
}

function Write-AsciiHeader {
    try {
        Write-Host ''
        $glyphs = Get-DazedPatcherBannerGlyphs
        $wordDazed = Build-AsciiWordLines -Word 'Dazed' -Glyphs $glyphs
        $wordPatcher = Build-AsciiWordLines -Word 'Patcher' -Glyphs $glyphs
        $titleCore = [System.Collections.Generic.List[string]]::new()
        foreach ($ln in $wordDazed) { $titleCore.Add($ln) }
        [void]$titleCore.Add('')
        foreach ($ln in $wordPatcher) { $titleCore.Add($ln) }
        $titleRows = $titleCore.ToArray()

        $catLines = @(Get-EmbeddedIconAsciiCatLines)

        $targetH = [Math]::Max($titleRows.Count, $catLines.Count)
        $titlePadded = Pad-LineBlockToHeight -Rows $titleRows -TargetHeight $targetH
        $catPadded = Pad-LineBlockToHeight -Rows $catLines -TargetHeight $targetH

        $titleWidth = 0
        foreach ($ln in $titlePadded) {
            $safe = if ($null -eq $ln) { '' } else { $ln }
            if ($safe.Length -gt $titleWidth) { $titleWidth = $safe.Length }
        }

        $gap = '    '
        for ($i = 0; $i -lt $targetH; $i++) {
            $ti = if ($null -eq $titlePadded[$i]) { '' } else { $titlePadded[$i] }
            $ci = if ($catPadded.Length -le $i -or $null -eq $catPadded[$i]) { '' } else { $catPadded[$i] }
            $left = if ($titleWidth -gt 0) { $ti.PadRight($titleWidth) } else { '' }
            Write-Host ($left + $gap + $ci)
        }
        Write-Host ''
    }
    catch {
        Write-Host ('[Banner skipped] ' + $_.Exception.Message)
    }
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

function Get-InvalidZipDownloadHint {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    $item = Get-Item -LiteralPath $LiteralPath -ErrorAction SilentlyContinue
    if (-not $item) {
        return '(downloaded file missing)'
    }
    $len = $item.Length
    $parts = [System.Collections.Generic.List[string]]::new()
    $parts.Add("File size: $len bytes.")
    if ($len -eq 0) {
        $parts.Add('Empty file often means the window was closed during download, the connection dropped, or security software blocked the file. Run again and let it finish.')
        return ($parts -join ' ')
    }

    $peekSize = [Math]::Min([int64]$len, 6144)
    $buf = New-Object byte[] $peekSize
    $fs = [System.IO.File]::OpenRead($LiteralPath)
    try {
        [void]$fs.Read($buf, 0, $peekSize)
    }
    finally {
        $fs.Dispose()
    }

    $text = [System.Text.Encoding]::UTF8.GetString($buf)
    if ($text -match '(?i)<!DOCTYPE\s+html|<html[\s>]') {
        $parts.Add('Body looks like HTML (often an error page or block). Check username/repo/branch in patch-config.txt and network.')
    }
    elseif ($text.TrimStart().StartsWith('{')) {
        try {
            $j = ($text.TrimStart() | ConvertFrom-Json)
            if ($j.message) {
                $parts.Add("GitLab JSON: $($j.message)")
            }
            else {
                $parts.Add('Body starts with JSON (likely an API error, not a ZIP).')
            }
        }
        catch {
            $parts.Add('Body starts with `{` but was not parseable JSON (truncated or wrong encoding).')
        }
    }
    else {
        $flat = ($text -replace '[\r\n]+', ' ')
        $take = [Math]::Min(200, $flat.Length)
        if ($take -gt 0) {
            $parts.Add(('UTF-8 preview: ' + $flat.Substring(0, $take)))
        }
    }

    return ($parts -join ' ')
}

$script:GameUpdateConsoleCloseHelperLoaded = $false
function Initialize-GameUpdateConsoleCloseHelper {
    if ($script:GameUpdateConsoleCloseHelperLoaded) { return }
    $script:GameUpdateConsoleCloseHelperLoaded = $true
    $script:GameUpdateConsoleCloseHelperWorks = $false
    if ($env:OS -ne 'Windows_NT') { return }

    try {
        Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;

namespace GameUpdate {
    public static class ConsoleCloseHelper {
        private static HandlerRoutine _handler;

        public static void Register() {
            _handler = Handle;
            SetConsoleCtrlHandler(_handler, true);
        }

        public static void Unregister() {
            if (_handler != null) {
                SetConsoleCtrlHandler(_handler, false);
                _handler = null;
            }
        }

        private static bool Handle(uint ctrlType) {
            const uint CTRL_CLOSE_EVENT = 2;
            const uint CTRL_LOGOFF_EVENT = 5;
            const uint CTRL_SHUTDOWN_EVENT = 6;
            if (ctrlType != CTRL_CLOSE_EVENT && ctrlType != CTRL_LOGOFF_EVENT && ctrlType != CTRL_SHUTDOWN_EVENT) {
                return false;
            }
            try {
                string path = Environment.GetEnvironmentVariable("GAMEUPDATE_REPO_ZIP_PATH");
                if (!string.IsNullOrEmpty(path) && File.Exists(path)) {
                    File.Delete(path);
                }
            }
            catch { }
            return false;
        }

        private delegate bool HandlerRoutine(uint ctrlType);

        [DllImport("Kernel32.dll", SetLastError = true)]
        private static extern bool SetConsoleCtrlHandler(HandlerRoutine handler, bool add);
    }
}
'@ -ErrorAction Stop
        $script:GameUpdateConsoleCloseHelperWorks = $true
    }
    catch {
        $script:GameUpdateConsoleCloseHelperWorks = $false
    }
}

function Invoke-PatchArchiveDownload {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$OutFile,
        [Parameter(Mandatory = $true)][hashtable]$Headers
    )

    if (Test-Path -LiteralPath $OutFile) {
        Remove-Item -LiteralPath $OutFile -Force
    }

    $outFull = [System.IO.Path]::GetFullPath($OutFile)
    Initialize-GameUpdateConsoleCloseHelper

    $prevPref = $ProgressPreference
    $completed = $false
    $registeredCloseHandler = $false
    try {
        if ($script:GameUpdateConsoleCloseHelperWorks) {
            $env:GAMEUPDATE_REPO_ZIP_PATH = $outFull
            [GameUpdate.ConsoleCloseHelper]::Register()
            $registeredCloseHandler = $true
        }

        $ProgressPreference = 'Continue'
        Invoke-WebRequest -Uri $Url -OutFile $OutFile -Headers $Headers -UseBasicParsing
        $completed = $true
    }
    finally {
        $ProgressPreference = $prevPref

        if ($registeredCloseHandler) {
            try {
                [GameUpdate.ConsoleCloseHelper]::Unregister()
            }
            catch { }
            Remove-Item env:GAMEUPDATE_REPO_ZIP_PATH -ErrorAction SilentlyContinue
        }

        if (-not $completed -and (Test-Path -LiteralPath $OutFile)) {
            Remove-FileOrDirectoryViaCmd -LiteralPath $OutFile
        }
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
    $headers = @{ 'User-Agent' = 'DazedMTL-Patcher-1.0' }
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

    $zipPath = Join-Path $Root ('dazedmtl_patch_' + [Guid]::NewGuid().ToString('N') + '.zip')
    Write-Host ('Downloading patch... ' + $zipPath)
    $stage = Join-Path ([IO.Path]::GetTempPath()) ('gu_' + [Guid]::NewGuid().ToString('N'))
    $archiveSha = [uri]::EscapeDataString($latestSha)
    $archiveUrl = "https://gitgud.io/api/v4/projects/$id/repository/archive.zip?sha=$archiveSha"

    $dlSw = [System.Diagnostics.Stopwatch]::StartNew()
    Invoke-WithRetry -Name 'Download archive with Invoke-WebRequest' -Attempts $dlAttempts -Action {
        Invoke-PatchArchiveDownload -Url $archiveUrl -OutFile $zipPath -Headers $headers
    } | Out-Null
    $dlSw.Stop()
    $bytes = (Get-Item -LiteralPath $zipPath).Length
    if ($bytes -eq 0) {
        $hint = Get-InvalidZipDownloadHint -LiteralPath $zipPath
        Remove-DownloadedRepoZip -LiteralPath $zipPath
        throw "PATCH_ERR:ZIP:Download is empty (0 bytes). $hint"
    }

    $secs = [Math]::Max($dlSw.Elapsed.TotalSeconds, 0.001)
    $mbps = ($bytes / 1MB) / $secs
    Write-Host ("Download complete: {0:N1} MB in {1:N1}s ({2:N1} MB/s)" -f ($bytes / 1MB), $secs, $mbps)

    $zipHeaderBad = $false
    $zipHeaderHint = ''
    $fs = [System.IO.File]::OpenRead($zipPath)
    try {
        $hdr = New-Object byte[] 4
        if ($fs.Read($hdr, 0, 4) -lt 4 -or $hdr[0] -ne 0x50 -or $hdr[1] -ne 0x4B) {
            $zipHeaderBad = $true
            $zipHeaderHint = Get-InvalidZipDownloadHint -LiteralPath $zipPath
        }
    }
    finally {
        $fs.Dispose()
    }
    if ($zipHeaderBad) {
        Remove-DownloadedRepoZip -LiteralPath $zipPath
        throw "PATCH_ERR:ZIP:Download is not a valid ZIP (missing PK header). $zipHeaderHint"
    }

    if (Test-Path -LiteralPath $stage) {
        Remove-FileOrDirectoryViaCmd -LiteralPath $stage
    }
    New-Item -ItemType Directory -Path $stage | Out-Null
    try {
        try {
            Expand-Archive -LiteralPath $zipPath -DestinationPath $stage -Force
            $dirs = @(Get-ChildItem -LiteralPath $stage -Directory)
            if ($dirs.Count -ne 1) {
                throw ('PATCH_ERR:ZIP:Expected one root folder in archive, found {0}.' -f $dirs.Count)
            }
            Copy-Item -Path (Join-Path $dirs[0].FullName '*') -Destination $PWD.Path -Recurse -Force
        }
        finally {
            if (Test-Path -LiteralPath $zipPath) {
                Remove-DownloadedRepoZip -LiteralPath $zipPath
            }
        }
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

function Remove-StalePatchZipArtifactsInGameRoot {
    param([Parameter(Mandatory = $true)][string]$Root)
    if (-not (Test-Path -LiteralPath $Root)) { return }
    Get-ChildItem -LiteralPath $Root -Filter 'dazedmtl_patch_*.zip' -File -ErrorAction SilentlyContinue |
        ForEach-Object {
            Remove-FileOrDirectoryViaCmd -LiteralPath $_.FullName
        }
}

function Remove-PatchTempArtifacts {
    param([string]$Root)
    $zipPath = Join-Path $Root 'repo.zip'
    $legacyTmp = Join-Path $Root '_patch_extract_tmp'

    Remove-StalePatchZipArtifactsInGameRoot -Root $Root

    if (Test-Path -LiteralPath $zipPath) {
        Write-Host '  Removing repo.zip...'
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

    Write-AsciiHeader

    Remove-StalePatchZipArtifactsInGameRoot -Root $GameRoot

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

    Write-Host ('Pulling patch from https://gitgud.io/{0}/{1} (branch: {2})' -f $cfg.username, $cfg.repo, $cfg.branch)

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
