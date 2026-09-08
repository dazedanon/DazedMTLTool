param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $ExtractorArgs
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

dotnet run --project (Join-Path $PSScriptRoot "TextExtractor") -- --root $Root @ExtractorArgs
