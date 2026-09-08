param(
    [string]$Config = (Join-Path $PSScriptRoot "..\config.json"),
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$cfg = Get-Content -Raw -Path $Config | ConvertFrom-Json
$tools = Join-Path $root "tools"
$downloads = Join-Path $tools "_downloads"
New-Item -ItemType Directory -Force -Path $tools,$downloads | Out-Null

function Download-Zip {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$Url,
        [Parameter(Mandatory=$true)][string]$Destination
    )

    if ((Test-Path $Destination) -and !$Force) {
        Write-Host "$Name already exists: $Destination"
        return
    }

    $archive = Join-Path $downloads ([System.IO.Path]::GetFileName($Url))
    Write-Host "Downloading $Name from $Url"
    Invoke-WebRequest -Uri $Url -OutFile $archive

    if (Test-Path $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Expand-Archive -LiteralPath $archive -DestinationPath $Destination -Force
}

function Download-File {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$Url,
        [Parameter(Mandatory=$true)][string]$Destination
    )

    if ((Test-Path $Destination) -and !$Force) {
        Write-Host "$Name already exists: $Destination"
        return
    }

    New-Item -ItemType Directory -Force -Path (Split-Path $Destination -Parent) | Out-Null
    Write-Host "Downloading $Name from $Url"
    Invoke-WebRequest -Uri $Url -OutFile $Destination
}

$retocVersion = $cfg.toolVersions.retoc
$repakVersion = $cfg.toolVersions.repak
$uassetGuiVersion = $cfg.toolVersions.uassetgui

Download-Zip "retoc" `
    "https://github.com/trumank/retoc/releases/download/$retocVersion/retoc_cli-x86_64-pc-windows-msvc.zip" `
    (Join-Path $tools "retoc")

Download-Zip "repak" `
    "https://github.com/trumank/repak/releases/download/$repakVersion/repak_cli-x86_64-pc-windows-msvc.zip" `
    (Join-Path $tools "repak")

Download-File "UAssetGUI" `
    "https://github.com/atenfyr/UAssetGUI/releases/download/$uassetGuiVersion/UAssetGUI.exe" `
    (Join-Path $tools "UAssetGUI\UAssetGUI.exe")

Write-Host "Bootstrap complete. Tool folders:"
Get-ChildItem -Path $tools -Directory | Select-Object FullName
