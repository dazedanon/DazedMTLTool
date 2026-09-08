param(
    [string] $Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Scratch = Join-Path $PSScriptRoot "scratch"

New-Item -ItemType Directory -Force -Path $Scratch | Out-Null

$env:DOTNET_CLI_HOME = $Scratch
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = "1"
$env:DOTNET_NOLOGO = "1"
$env:DOTNET_CLI_TELEMETRY_OPTOUT = "1"
$env:DOTNET_ADD_GLOBAL_TOOLS_TO_PATH = "false"
$env:NUGET_PACKAGES = "C:\Users\sw\.nuget\packages"

$KnownTextsSource = Join-Path $PSScriptRoot "outputs\japanese_text_all_occurrences.csv"
$KnownTextsDir = Join-Path $PSScriptRoot "LoserLifeATest\translations"
$KnownTextsPath = Join-Path $KnownTextsDir "known_texts.b64"

if (Test-Path $KnownTextsSource) {
    New-Item -ItemType Directory -Force -Path $KnownTextsDir | Out-Null
    $rows = Import-Csv $KnownTextsSource
    $set = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    foreach ($row in $rows) {
        $text = [string] $row.text
        if ([string]::IsNullOrWhiteSpace($text)) {
            continue
        }

        $text = $text.Replace("`r`n", "`n").Replace("`r", "`n").Replace([string][char]0x200B, "").Trim()
        [void] $set.Add($text)
    }

    $encoded = foreach ($text in $set) {
        [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($text))
    }
    $encoded | Set-Content -Encoding ASCII $KnownTextsPath
    Write-Host "Generated known text list: $($set.Count) strings"
}

dotnet build (Join-Path $PSScriptRoot "LoserLifeATest") `
    -c $Configuration `
    --ignore-failed-sources `
    -p:GameDir="$Root" `
    -p:RestoreIgnoreFailedSources=true `
    -p:NuGetAudit=false
