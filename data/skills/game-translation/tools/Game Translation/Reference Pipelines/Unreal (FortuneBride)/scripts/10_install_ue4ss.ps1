param(
    [string]$GameRoot = "",
    [string]$Win64Dir = "",
    [string]$DownloadUrl = "",
    [string]$Version = "experimental-latest",
    [string]$DownloadDir = "",
    [switch]$ForceDownload,
    [switch]$RootLayout,
    [switch]$SkipTextHook,
    [switch]$EnableTextHook
)

$ErrorActionPreference = "Stop"
$toolRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (!$GameRoot) { $GameRoot = (Resolve-Path (Join-Path $toolRoot "..")).Path }
if (!$Win64Dir) { $Win64Dir = Join-Path $GameRoot "StoryFramework\Binaries\Win64" }
if (!$DownloadDir) { $DownloadDir = Join-Path $toolRoot "downloads\ue4ss" }

if (!(Test-Path $Win64Dir)) { throw "Missing game Win64 directory at $Win64Dir" }
New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null

if (!$DownloadUrl) {
    $headers = @{ "User-Agent" = "Codex-Ikisaw-Tooling" }
    $releaseUri = if ($Version -eq "latest") {
        "https://api.github.com/repos/UE4SS-RE/RE-UE4SS/releases/latest"
    } else {
        "https://api.github.com/repos/UE4SS-RE/RE-UE4SS/releases/tags/$Version"
    }
    Write-Host "Querying UE4SS release metadata..."
    $release = Invoke-RestMethod -Headers $headers -Uri $releaseUri
    $asset = @($release.assets | Where-Object { $_.name -match "^UE4SS_v.*\.zip$" } | Select-Object -First 1)
    if (!$asset) { throw "Could not find a normal UE4SS_v*.zip asset in release $($release.tag_name)." }
    $DownloadUrl = $asset.browser_download_url
}

$zipName = Split-Path ([Uri]$DownloadUrl).AbsolutePath -Leaf
$zipPath = Join-Path $DownloadDir $zipName
if ($ForceDownload -or !(Test-Path $zipPath)) {
    Write-Host "Downloading $zipName..."
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $zipPath
} else {
    Write-Host "Using cached $zipPath"
}

$extractDir = Join-Path $DownloadDir ([IO.Path]::GetFileNameWithoutExtension($zipName))
if (Test-Path $extractDir) { Remove-Item -LiteralPath $extractDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $extractDir | Out-Null
Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force

$dwmapi = Get-ChildItem -Path $extractDir -Filter "dwmapi.dll" -Recurse | Select-Object -First 1
if (!$dwmapi) { throw "UE4SS proxy DLL dwmapi.dll was not found in $zipName" }
Copy-Item -LiteralPath $dwmapi.FullName -Destination (Join-Path $Win64Dir "dwmapi.dll") -Force

$sourceUe4ssDir = Get-ChildItem -Path $extractDir -Directory -Recurse | Where-Object { $_.Name -ieq "ue4ss" } | Select-Object -First 1
$destUe4ssDir = if ($RootLayout) { $Win64Dir } else { Join-Path $Win64Dir "ue4ss" }
New-Item -ItemType Directory -Force -Path $destUe4ssDir | Out-Null

if ($sourceUe4ssDir) {
    Get-ChildItem -LiteralPath $sourceUe4ssDir.FullName -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $destUe4ssDir -Recurse -Force
    }
} else {
    $ue4ssDll = Get-ChildItem -Path $extractDir -Filter "UE4SS.dll" -Recurse | Select-Object -First 1
    if (!$ue4ssDll) { throw "UE4SS.dll was not found in $zipName" }
    Copy-Item -LiteralPath $ue4ssDll.FullName -Destination (Join-Path $destUe4ssDir "UE4SS.dll") -Force

    $settings = Get-ChildItem -Path $extractDir -Filter "UE4SS-settings.ini" -Recurse | Select-Object -First 1
    if ($settings) { Copy-Item -LiteralPath $settings.FullName -Destination (Join-Path $destUe4ssDir "UE4SS-settings.ini") -Force }

    $mods = Get-ChildItem -Path $extractDir -Directory -Recurse | Where-Object { $_.Name -ieq "Mods" } | Select-Object -First 1
    if ($mods) {
        Copy-Item -LiteralPath $mods.FullName -Destination $destUe4ssDir -Recurse -Force
    } else {
        New-Item -ItemType Directory -Force -Path (Join-Path $destUe4ssDir "Mods") | Out-Null
    }
}

$modsDir = Join-Path $destUe4ssDir "Mods"
New-Item -ItemType Directory -Force -Path $modsDir | Out-Null
if (!(Test-Path (Join-Path $modsDir "mods.txt"))) {
    Set-Content -Path (Join-Path $modsDir "mods.txt") -Encoding ASCII -Value @(
        "BPModLoaderMod : 0",
        "ConsoleEnablerMod : 1",
        "ConsoleCommandsMod : 1",
        "IkisawTextHook : 0",
        "",
        "; Built-in keybinds, keep this at the bottom if UE4SS created it.",
        "Keybinds : 1"
    )
}

if (!$SkipTextHook) {
    & (Join-Path $PSScriptRoot "09_install_ue4ss_text_hook.ps1") -GameRoot $GameRoot -ModsDir $modsDir -Enable:$EnableTextHook
}

Write-Host "Installed UE4SS from $zipName"
Write-Host "Proxy: $(Join-Path $Win64Dir "dwmapi.dll")"
Write-Host "UE4SS: $destUe4ssDir"
Write-Host "Mods: $modsDir"
