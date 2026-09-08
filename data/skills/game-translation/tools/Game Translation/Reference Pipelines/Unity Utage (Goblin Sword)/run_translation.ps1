param(
    [switch]$DryRun,
    [switch]$MergeOnly,
    [int]$MaxRows = 0,
    [int]$MaxUnits = 0,
    [string]$Model = "mistral-medium-3-5",
    [int]$BatchSize = 40,
    [int]$MaxLinesPerRequest = 90,
    [int]$MaxCharsPerRequest = 36000,
    [int]$MaxTokens = 16384,
    [double]$LiveSleepSeconds = 1.0,
    [double]$RequestsPerMinute = 0,
    [int]$RetryDelayMs = 15000,
    [string]$InputJson = "",
    [ValidateSet("auto", "utage-scenes", "utage-flat", "records", "non-dialogue")]
    [string]$InputType = "auto",
    [string]$OutputJsonl = "",
    [string]$FailedJsonl = "",
    [string]$MergedJson = "",
    [string]$DryrunJsonl = "",
    [string[]]$Kind = @(),
    [string[]]$Category = @(),
    [string]$SourceContains = "",
    [switch]$OnlyEmpty,
    [switch]$NoResume,
    [switch]$NoCjkCheck,
    [switch]$StrictValidation,
    [switch]$StopOnFailure,
    [switch]$SkipExtract
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$script = Join-Path $PSScriptRoot "translate_mistral.py"
if (-not (Test-Path $script)) {
    throw "Missing runner: $script"
}

$gameRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$defaultInputJson = Join-Path $gameRoot "tooling\utage_dialogue_scenes.json"
$inputJson = if ([string]::IsNullOrWhiteSpace($InputJson)) { $defaultInputJson } else { $InputJson }

if (-not (Test-Path $inputJson)) {
    throw "Missing Unity/Utage translation input: $inputJson. Run tooling\extract_utage_dialogue.py first."
}

if (-not $DryRun -and -not $MergeOnly -and [string]::IsNullOrWhiteSpace($env:MISTRAL_API_KEY)) {
    throw "MISTRAL_API_KEY is not set. Run `$env:MISTRAL_API_KEY = 'your_key_here' first, or use -DryRun."
}

$argsList = @(
    $script,
    "--model", $Model,
    "--input-json", $inputJson,
    "--input-type", $InputType,
    "--batch-size", "$BatchSize",
    "--max-lines-per-request", "$MaxLinesPerRequest",
    "--max-chars-per-request", "$MaxCharsPerRequest",
    "--max-tokens", "$MaxTokens",
    "--live-sleep-seconds", "$LiveSleepSeconds",
    "--requests-per-minute", "$RequestsPerMinute",
    "--retry-delay-ms", "$RetryDelayMs"
)

if ($DryRun) { $argsList += "--dry-run" }
if ($MergeOnly) { $argsList += "--merge-only" }
if ($MaxRows -gt 0) { $argsList += @("--max-rows", "$MaxRows") }
if ($MaxUnits -gt 0) { $argsList += @("--max-units", "$MaxUnits") }
if (-not [string]::IsNullOrWhiteSpace($OutputJsonl)) { $argsList += @("--output-jsonl", $OutputJsonl) }
if (-not [string]::IsNullOrWhiteSpace($FailedJsonl)) { $argsList += @("--failed-jsonl", $FailedJsonl) }
if (-not [string]::IsNullOrWhiteSpace($MergedJson)) { $argsList += @("--merged-json", $MergedJson) }
if (-not [string]::IsNullOrWhiteSpace($DryrunJsonl)) { $argsList += @("--dryrun-jsonl", $DryrunJsonl) }
foreach ($kindName in $Kind) {
    if (-not [string]::IsNullOrWhiteSpace($kindName)) { $argsList += @("--kind", $kindName) }
}
foreach ($categoryName in $Category) {
    if (-not [string]::IsNullOrWhiteSpace($categoryName)) { $argsList += @("--category", $categoryName) }
}
if (-not [string]::IsNullOrWhiteSpace($SourceContains)) { $argsList += @("--source-contains", $SourceContains) }
if ($OnlyEmpty) { $argsList += "--only-empty" }
if ($NoResume) { $argsList += "--no-resume" }
if ($NoCjkCheck) { $argsList += "--no-cjk-check" }
if ($StrictValidation) { $argsList += "--strict-validation" }
if ($StopOnFailure) { $argsList += "--stop-on-failure" }

& python @argsList
