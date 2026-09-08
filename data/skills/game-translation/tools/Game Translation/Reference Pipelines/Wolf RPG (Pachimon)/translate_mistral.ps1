[CmdletBinding()]
param(
    [string]$InputCsv = "",
    [string]$OutputJsonl = "",
    [string]$FailedJsonl = "",
    [string]$PromptPath = "",
    [string]$GlossaryPath = "",
    [string]$ApiKey = $env:MISTRAL_API_KEY,
    [string]$Endpoint = "https://api.mistral.ai/v1/chat/completions",
    [string]$Model = "mistral-medium-3-5",
    [ValidateSet("none", "high")]
    [string]$ReasoningEffort = "none",
    [string]$TargetLanguage = "English",
    [int]$BatchSize = 12,
    [int]$MaxRows = 0,
    [int]$StartAfterId = 0,
    [int]$MaxRetries = 2,
    [int]$EndRetryRounds = 5,
    [int]$SleepMs = 1000,
    [int]$RetryDelayMs = 15000,
    [int]$MaxTokens = 4096,
    [int]$HistorySize = 10,
    [double]$Temperature = 0.15,
    [switch]$MapOnly,
    [switch]$CommonOnly,
    [switch]$NoDedupe,
    [switch]$NoEndRetry,
    [switch]$NoResume,
    [switch]$DryRun,
    [switch]$StopOnFailure
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($InputCsv)) {
    $InputCsv = Join-Path $PSScriptRoot "..\..\TextExport\strings_japanese.csv"
}
if ([string]::IsNullOrWhiteSpace($OutputJsonl)) {
    $OutputJsonl = Join-Path $PSScriptRoot "..\..\TextExport\mistral_fullgame_translations.jsonl"
}
if ([string]::IsNullOrWhiteSpace($FailedJsonl)) {
    $FailedJsonl = Join-Path $PSScriptRoot "..\..\TextExport\mistral_fullgame_translations.failed.jsonl"
}
if ([string]::IsNullOrWhiteSpace($PromptPath)) {
    $PromptPath = Join-Path $PSScriptRoot "prompt.md"
}
if ([string]::IsNullOrWhiteSpace($GlossaryPath)) {
    $GlossaryPath = Join-Path $PSScriptRoot "glossary.md"
}

$InputCsv = [System.IO.Path]::GetFullPath($InputCsv)
$OutputJsonl = [System.IO.Path]::GetFullPath($OutputJsonl)
$FailedJsonl = [System.IO.Path]::GetFullPath($FailedJsonl)
$PromptPath = [System.IO.Path]::GetFullPath($PromptPath)
$GlossaryPath = [System.IO.Path]::GetFullPath($GlossaryPath)
$Utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false

function Convert-ExportText {
    param([object]$Value)
    if ($null -eq $Value) {
        return ""
    }
    $s = [string]$Value
    $s = $s.Replace('\r', "`r")
    $s = $s.Replace('\n', "`n")
    $s = $s.Replace('\t', "`t")
    $s = $s.Replace('\\', '\')
    return $s
}

function Get-TokenMap {
    param([string]$Tokens)
    $map = [ordered]@{}
    if ([string]::IsNullOrWhiteSpace($Tokens)) {
        return $map
    }

    $parts = $Tokens -split '\s+\|\s+'
    $index = 1
    foreach ($part in $parts) {
        $map["CTRL$index"] = Convert-ExportText $part
        $index += 1
    }
    return $map
}

function Test-JapaneseText {
    param([string]$Text)
    return [regex]::IsMatch([string]$Text, '[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]')
}

function Protect-SourceText {
    param([string]$Text)

    $source = Convert-ExportText $Text
    $tokens = [ordered]@{}
    $index = 1
    $pattern = '(__PROTECTED_\d+__|#[0-9A-Fa-f]{6}|\\(?:[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?|[.!|><^{}\\])|@\d+|[A-Za-z0-9_./\\-]+\.(?:png|jpg|jpeg|bmp|webp|ogg|wav|mps|dat|ttf|txt|json|wolf))'
    $template = [regex]::Replace($source, $pattern, {
        param($match)
        $key = "CTRL$index"
        $tokens[$key] = $match.Value
        $index += 1
        return "{$key}"
    })

    return [pscustomobject]@{
        Template = $template
        Tokens = $tokens
    }
}

function Get-PlaceholderCounts {
    param([string]$Text)
    $counts = @{}
    foreach ($match in [regex]::Matches([string]$Text, '\{CTRL\d+\}')) {
        $key = $match.Value
        if (-not $counts.ContainsKey($key)) {
            $counts[$key] = 0
        }
        $counts[$key] += 1
    }
    return $counts
}

function Test-TranslationPlaceholders {
    param(
        [string]$Source,
        [string]$Translation,
        [ref]$Reason
    )

    $sourceCounts = Get-PlaceholderCounts $Source
    $translationCounts = Get-PlaceholderCounts $Translation
    $allKeys = @($sourceCounts.Keys + $translationCounts.Keys | Sort-Object -Unique)
    foreach ($key in $allKeys) {
        $sourceCount = 0
        $translationCount = 0
        if ($sourceCounts.ContainsKey($key)) {
            $sourceCount = $sourceCounts[$key]
        }
        if ($translationCounts.ContainsKey($key)) {
            $translationCount = $translationCounts[$key]
        }
        if ($sourceCount -ne $translationCount) {
            $Reason.Value = "placeholder $key count mismatch: source=$sourceCount translation=$translationCount"
            return $false
        }
    }

    if ([regex]::IsMatch($Translation, '\\(?:[A-Za-z_][A-Za-z0-9_]*\[[^\]]*\]|[.!><^])')) {
        $Reason.Value = "raw WOLF control code leaked into translation"
        return $false
    }

    if (Test-JapaneseText $Translation) {
        $Reason.Value = "Japanese text remains in translation"
        return $false
    }

    $Reason.Value = ""
    return $true
}

function Append-JsonLine {
    param(
        [string]$Path,
        [object]$Object
    )
    $json = $Object | ConvertTo-Json -Depth 100 -Compress
    [System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($Path)) | Out-Null
    [System.IO.File]::AppendAllText($Path, $json + [Environment]::NewLine, $Utf8NoBom)
}

function Read-DoneIds {
    param([string]$Path)
    $done = @{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return $done
    }

    foreach ($line in [System.IO.File]::ReadLines($Path)) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        try {
            $item = $line | ConvertFrom-Json
            if ($item.id) {
                $done[[string]$item.id] = $true
            }
        } catch {
            Write-Warning "Skipping malformed existing JSONL line in $Path"
        }
    }
    return $done
}

function Read-TranslationHistory {
    param(
        [string]$Path,
        [int]$Limit
    )

    $history = New-Object System.Collections.ArrayList
    if ($Limit -le 0 -or -not (Test-Path -LiteralPath $Path)) {
        return $history
    }

    foreach ($line in [System.IO.File]::ReadLines($Path)) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        try {
            $item = $line | ConvertFrom-Json
            if ($item.source_template -and $item.translation_template) {
                $entry = [ordered]@{
                    speaker = [string]$item.speaker
                    source_template = [string]$item.source_template
                    translation_template = [string]$item.translation_template
                }
                [void]$history.Add($entry)
                while ($history.Count -gt $Limit) {
                    $history.RemoveAt(0)
                }
            }
        } catch {
            Write-Warning "Skipping malformed existing JSONL line while loading history from $Path"
        }
    }
    return $history
}

function Convert-RowToLine {
    param([object]$Row)

    $columns = @($Row.PSObject.Properties.Name)
    if ($columns -contains "dialogue_template") {
        $template = Convert-ExportText $Row.dialogue_template
        if ([string]::IsNullOrWhiteSpace($template)) {
            $template = Convert-ExportText $Row.dialogue
        }

        return [ordered]@{
            id = [string]$Row.id
            file = [string]$Row.file
            source = [string]$Row.source
            context = [string]$Row.context
            kind = "dialogue"
            purpose = "dialogue_or_message"
            event = [ordered]@{
                id = [string]$Row.event_id
                name = [string]$Row.event_name
                page = [string]$Row.page_id
            }
            command_index = [string]$Row.command_index
            offset = [ordered]@{
                command = [string]$Row.command_offset_hex
                string = [string]$Row.string_offset_hex
            }
            speaker = [string]$Row.speaker
            visible_source = Convert-ExportText $Row.dialogue
            source_template = $template
            tokens = Get-TokenMap $Row.tokens
        }
    }

    $protected = Protect-SourceText $Row.text
    $visibleSource = Convert-ExportText $Row.text
    $purpose = Get-LinePurpose -File ([string]$Row.file) -Text $visibleSource
    return [ordered]@{
        id = [string]$Row.id
        file = [string]$Row.file
        source = "string"
        context = "offset:$($Row.offset_hex)"
        kind = [string]$Row.kind
        purpose = $purpose
        event = [ordered]@{
            id = ""
            name = ""
            page = ""
        }
        command_index = ""
        offset = [ordered]@{
            command = ""
            string = [string]$Row.offset_hex
        }
        speaker = ""
        visible_source = $visibleSource
        source_template = $protected.Template
        tokens = $protected.Tokens
    }
}

function Get-LinePurpose {
    param(
        [string]$File,
        [string]$Text
    )

    $lower = $File.ToLowerInvariant()
    $plain = $Text.Trim()
    $charCount = $plain.Length
    if ($lower.EndsWith("game.dat")) {
        return "game_title_or_global_config"
    }
    if ($lower.Contains("database") -or $lower.Contains("sysdatabase") -or $lower.Contains("cdatabase")) {
        if ($charCount -le 28 -and -not $plain.Contains("`n")) {
            return "database_name_or_ui_label"
        }
        return "database_description_or_system_text"
    }
    if ($lower.Contains("mapdata/") -or $lower.Contains("mapdata\")) {
        if ($charCount -le 28 -and -not $plain.Contains("`n")) {
            return "map_label_sign_or_choice"
        }
        return "map_event_text"
    }
    if ($charCount -le 28 -and -not $plain.Contains("`n")) {
        return "short_name_or_ui_label"
    }
    return "generic_game_text"
}

function New-Batches {
    param(
        [object[]]$Jobs,
        [int]$Size
    )

    $batches = New-Object System.Collections.Generic.List[object]
    $current = @()
    $currentKey = $null

    foreach ($job in $Jobs) {
        $row = $job.Row
        $key = "$($row.file)|$($row.context)"
        if ($current.Count -gt 0 -and (($current.Count -ge $Size) -or ($key -ne $currentKey))) {
            $batches.Add(@($current))
            $current = @()
        }
        $current += $job
        $currentKey = $key
    }

    if ($current.Count -gt 0) {
        $batches.Add(@($current))
    }

    return $batches
}

function Get-TranslationKey {
    param([object]$Row)
    $line = Convert-RowToLine $Row
    $tokenJson = $line.tokens | ConvertTo-Json -Depth 20 -Compress
    return ([string]$line.speaker) + "`t" + ([string]$line.source_template) + "`t" + $tokenJson
}

function New-TranslationJobs {
    param(
        [object[]]$Rows,
        [switch]$DisableDedupe
    )

    $jobs = New-Object System.Collections.Generic.List[object]
    if ($DisableDedupe) {
        foreach ($row in $Rows) {
            $jobs.Add([pscustomobject]@{
                Row = $row
                Rows = @($row)
            })
        }
        return $jobs
    }

    $byKey = @{}
    foreach ($row in $Rows) {
        $key = Get-TranslationKey $row
        if (-not $byKey.ContainsKey($key)) {
            $entry = [pscustomobject]@{
                Row = $row
                Rows = New-Object System.Collections.ArrayList
            }
            [void]$entry.Rows.Add($row)
            $byKey[$key] = $entry
            $jobs.Add($entry)
        } else {
            [void]$byKey[$key].Rows.Add($row)
        }
    }

    return $jobs
}

function Get-ResponseContent {
    param([object]$Response)

    $content = $Response.choices[0].message.content
    if ($content -is [string]) {
        return $content
    }
    if ($content -is [System.Collections.IEnumerable]) {
        $parts = @()
        foreach ($part in $content) {
            if ($part.text) {
                $parts += [string]$part.text
            } elseif ($part.content) {
                $parts += [string]$part.content
            }
        }
        return ($parts -join "")
    }
    return ($content | ConvertTo-Json -Depth 20 -Compress)
}

function Get-RetryDelay {
    param([int]$Attempt)
    if ($RetryDelayMs -le 0) {
        return 0
    }
    $multiplier = [Math]::Pow(2, [Math]::Max(0, $Attempt - 1))
    $delay = [int]([Math]::Min($RetryDelayMs * $multiplier, 300000))
    return $delay
}

function Get-ProgressPercent {
    param(
        [int]$Completed,
        [int]$Total
    )

    if ($Total -le 0) {
        return 100
    }
    return [int]([Math]::Min(100, [Math]::Floor(($Completed * 100.0) / $Total)))
}

function Get-ProgressPercentText {
    param(
        [int]$Completed,
        [int]$Total
    )

    if ($Total -le 0) {
        return "100.00%"
    }
    return ("{0:N2}%" -f (($Completed * 100.0) / $Total))
}

function Format-Duration {
    param([double]$Seconds)

    if ($Seconds -lt 0 -or [double]::IsNaN($Seconds) -or [double]::IsInfinity($Seconds)) {
        return "--"
    }
    $totalSeconds = [int][Math]::Ceiling($Seconds)
    if ($totalSeconds -lt 60) {
        return ("{0}s" -f $totalSeconds)
    }

    $span = [TimeSpan]::FromSeconds($totalSeconds)
    if ($span.TotalDays -ge 1) {
        return ("{0}d {1:D2}h" -f [int]$span.TotalDays, $span.Hours)
    }
    if ($span.TotalHours -ge 1) {
        return ("{0}h {1:D2}m" -f [int]$span.TotalHours, $span.Minutes)
    }
    return ("{0}m {1:D2}s" -f $span.Minutes, $span.Seconds)
}

function Get-EtaText {
    if ($script:apiRowsTotal -le 0 -or $script:apiSecondsTotal -le 0) {
        return "--"
    }

    $remaining = [Math]::Max(0, $script:totalTextRows - $script:completedTextRows)
    if ($remaining -le 0) {
        return "0s"
    }

    $secondsPerRow = $script:apiSecondsTotal / $script:apiRowsTotal
    return (Format-Duration ($remaining * $secondsPerRow))
}

function Get-ConsoleWidth {
    try {
        $width = [int]$Host.UI.RawUI.WindowSize.Width
        if ($width -gt 40) {
            return $width
        }
    } catch {
    }
    return 120
}

function Get-ShortProgressLabel {
    param(
        [string]$Label,
        [int]$MaxLength
    )

    if ([string]::IsNullOrWhiteSpace($Label)) {
        $Label = "translation"
    }
    if ($MaxLength -lt 8) {
        $MaxLength = 8
    }
    if ($Label.Length -le $MaxLength) {
        return $Label
    }
    return "..." + $Label.Substring($Label.Length - ($MaxLength - 3))
}

function Complete-ConsoleProgressLine {
    if ($script:progressLineActive) {
        Write-Host ""
        $script:progressLineActive = $false
    }
}

function Write-ConsoleProgressBar {
    param(
        [int]$Completed,
        [int]$Total,
        [string]$Label,
        [string]$Status = "",
        [switch]$NewLine
    )

    $percent = Get-ProgressPercent -Completed $Completed -Total $Total
    $percentText = Get-ProgressPercentText -Completed $Completed -Total $Total
    $counter = "$Completed/$Total ($percentText)"
    $eta = Get-EtaText
    $tail = "$counter | ETA $eta"
    if (-not [string]::IsNullOrWhiteSpace($Status)) {
        $tail = "$tail | $Status"
    }
    $barWidth = 30
    $filled = [int]([Math]::Floor(($barWidth * $percent) / 100.0))
    $empty = $barWidth - $filled
    $consoleWidth = Get-ConsoleWidth
    $labelMax = [Math]::Max(16, $consoleWidth - $barWidth - $tail.Length - 8)
    $shortLabel = Get-ShortProgressLabel -Label $Label -MaxLength $labelMax

    Write-Host -NoNewline "`r$shortLabel ("
    if ($filled -gt 0) {
        Write-Host -NoNewline (" " * $filled) -BackgroundColor White
    }
    if ($empty -gt 0) {
        Write-Host -NoNewline (" " * $empty) -BackgroundColor DarkGray
    }
    Write-Host -NoNewline ") $tail"

    $usedWidth = $shortLabel.Length + 2 + $barWidth + 2 + $tail.Length
    $clearWidth = [Math]::Max(0, $consoleWidth - $usedWidth - 1)
    if ($clearWidth -gt 0) {
        Write-Host -NoNewline (" " * $clearWidth)
    }

    if ($NewLine) {
        Write-Host ""
        $script:progressLineActive = $false
    } else {
        $script:progressLineActive = $true
    }
}

function Write-TranslationProgress {
    param(
        [int]$Completed,
        [int]$Total,
        [string]$Status,
        [string]$Label = "",
        [int]$BatchNumber = 0,
        [int]$BatchTotal = 0,
        [string]$LineStatus = "",
        [switch]$NewLine
    )

    $percent = Get-ProgressPercent -Completed $Completed -Total $Total
    $percentText = Get-ProgressPercentText -Completed $Completed -Total $Total
    $counter = "$Completed/$Total text rows"
    if ($BatchTotal -gt 0) {
        $counter = "$counter | batch $BatchNumber/$BatchTotal"
    }

    Write-Progress -Activity "Mistral translation" -Status "$Status - $counter ($percentText)" -CurrentOperation $counter -PercentComplete $percent
    if ([string]::IsNullOrWhiteSpace($LineStatus)) {
        $LineStatus = $Status
    }
    Write-ConsoleProgressBar -Completed $Completed -Total $Total -Label $Label -Status $LineStatus -NewLine:$NewLine
}

function Wait-RetryWithProgress {
    param(
        [int]$Milliseconds,
        [string]$Label,
        [string]$Status,
        [int]$BatchNumber = 0,
        [int]$BatchTotal = 0
    )

    $remainingMs = [Math]::Max(0, $Milliseconds)
    while ($remainingMs -gt 0) {
        $retryText = Format-Duration ([Math]::Ceiling($remainingMs / 1000.0))
        Write-TranslationProgress -Completed $script:completedTextRows -Total $script:totalTextRows -Status $Status -Label $Label -BatchNumber $BatchNumber -BatchTotal $BatchTotal -LineStatus "$Status; retry in $retryText"
        $sleepMs = [Math]::Min(1000, $remainingMs)
        Start-Sleep -Milliseconds $sleepMs
        $remainingMs -= $sleepMs
    }
}

function Invoke-MistralBatch {
    param(
        [string]$SystemPrompt,
        [object]$BatchPayload,
        [string]$ValidationHint
    )

    $shape = '{"translations":[{"id":"same id as input","speaker_translation":"translated visible speaker name or empty string","translation_template":"English translation preserving every {CTRLn} placeholder"}]}'
    $batchJson = $BatchPayload | ConvertTo-Json -Depth 100
    $userPrompt = @"
Translate this batch to $TargetLanguage.

Return JSON only in this exact shape:
$shape

Validation hint from previous attempt:
$ValidationHint

Batch:
$batchJson
"@

    $bodyObject = [ordered]@{
        model = $Model
        temperature = $Temperature
        max_tokens = $MaxTokens
        response_format = @{ type = "json_object" }
        messages = @(
            @{ role = "system"; content = $SystemPrompt },
            @{ role = "user"; content = $userPrompt }
        )
    }
    if (($Model -eq "mistral-medium-3-5" -or $Model -eq "mistral-small-latest") -and $ReasoningEffort -eq "high") {
        $bodyObject.reasoning_effort = $ReasoningEffort
    }

    $bodyJson = $bodyObject | ConvertTo-Json -Depth 100
    $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($bodyJson)
    return Invoke-RestMethod -Uri $Endpoint -Method Post -Headers @{ Authorization = "Bearer $ApiKey" } -ContentType "application/json; charset=utf-8" -Body $bodyBytes
}

if (-not (Test-Path -LiteralPath $InputCsv)) {
    throw "Input CSV not found: $InputCsv"
}
if (-not (Test-Path -LiteralPath $PromptPath)) {
    throw "Prompt file not found: $PromptPath"
}
if (-not (Test-Path -LiteralPath $GlossaryPath)) {
    throw "Glossary file not found: $GlossaryPath"
}
if (-not $DryRun -and [string]::IsNullOrWhiteSpace($ApiKey)) {
    throw "MISTRAL_API_KEY is not set. Set `$env:MISTRAL_API_KEY or pass -ApiKey."
}
if ($BatchSize -lt 1) {
    throw "BatchSize must be at least 1."
}

$prompt = Get-Content -LiteralPath $PromptPath -Raw -Encoding UTF8
$glossary = Get-Content -LiteralPath $GlossaryPath -Raw -Encoding UTF8
$systemPrompt = $prompt.Trim() + "`n`n" + $glossary.Trim()

$rows = @(Import-Csv -LiteralPath $InputCsv -Encoding UTF8)
$columns = if ($rows.Count -gt 0) { @($rows[0].PSObject.Properties.Name) } else { @() }
$inputKind = if ($columns -contains "dialogue_template") {
    "dialogue"
} elseif ($columns -contains "text") {
    "strings"
} else {
    throw "Input CSV is not recognized. Expected dialogue_template or text column: $InputCsv"
}

if ($inputKind -eq "dialogue") {
    $rows = @($rows | Where-Object { -not [string]::IsNullOrWhiteSpace($_.dialogue_template) })
} else {
    $rows = @($rows | Where-Object { -not [string]::IsNullOrWhiteSpace($_.text) -and (Test-JapaneseText (Convert-ExportText $_.text)) })
}
if ($MapOnly) {
    $rows = @($rows | Where-Object { $inputKind -eq "dialogue" -and $_.source -eq "map" })
}
if ($CommonOnly) {
    $rows = @($rows | Where-Object { $inputKind -eq "dialogue" -and $_.source -like "common_event*" })
}
if ($StartAfterId -gt 0) {
    $rows = @($rows | Where-Object { [int]$_.id -gt $StartAfterId })
}
if ($MaxRows -gt 0) {
    $rows = @($rows | Select-Object -First $MaxRows)
}

$done = @{}
if (-not $NoResume -and -not $DryRun) {
    $done = Read-DoneIds $OutputJsonl
}
$pending = @($rows | Where-Object { -not $done.ContainsKey([string]$_.id) })
$jobs = @(New-TranslationJobs -Rows $pending -DisableDedupe:$NoDedupe)
$batches = @(New-Batches -Jobs $jobs -Size $BatchSize)
$totalTextRows = $rows.Count
$completedTextRows = @($rows | Where-Object { $done.ContainsKey([string]$_.id) }).Count
$script:progressLineActive = $false
$script:apiRowsTotal = 0
$script:apiSecondsTotal = 0.0
$script:apiRequestCount = 0
$script:lastApiSeconds = 0.0
$initialProgressLabel = if ($pending.Count -gt 0) { [string](Convert-RowToLine $pending[0]).file } else { $InputCsv }

Write-Host "input rows: $($rows.Count)"
Write-Host "input kind: $inputKind"
Write-Host "pending rows: $($pending.Count)"
Write-Host "translation jobs: $($jobs.Count)"
if (-not $NoDedupe) {
    Write-Host "deduped rows saved: $($pending.Count - $jobs.Count)"
}
Write-Host "batches: $($batches.Count)"
Write-Host "model: $Model"
Write-Host "reasoning_effort: $ReasoningEffort"
Write-TranslationProgress -Completed $completedTextRows -Total $totalTextRows -Status "starting" -Label $initialProgressLabel -NewLine

if ($DryRun) {
    $previewPath = [System.IO.Path]::ChangeExtension($OutputJsonl, ".dryrun.jsonl")
    if (Test-Path -LiteralPath $previewPath) {
        Remove-Item -LiteralPath $previewPath
    }
    $batchIndex = 0
    foreach ($batchJobs in $batches) {
        $batchIndex += 1
        $lines = @($batchJobs | ForEach-Object { Convert-RowToLine $_.Row })
        $payload = [ordered]@{
            batch_id = "batch-$batchIndex"
            target_language = $TargetLanguage
            note = "Lines are in extracted file order. Translate source_template; use visible_source and metadata only as aid."
            translation_history = @()
            lines = $lines
        }
        Append-JsonLine -Path $previewPath -Object $payload
    }
    Write-Host "dry-run batches written: $previewPath"
    exit 0
}

$history = if (-not $NoResume) {
    Read-TranslationHistory -Path $OutputJsonl -Limit $HistorySize
} else {
    New-Object System.Collections.ArrayList
}
if ($history.Count -gt 0) {
    Write-Host "loaded translation history: $($history.Count)"
}

function Invoke-TranslationBatchSet {
    param(
        [object[]]$BatchSet,
        [string]$PassLabel
    )

    $batchNumber = 0
    foreach ($batchJobs in $BatchSet) {
        $batchNumber += 1
        $lines = @($batchJobs | ForEach-Object { Convert-RowToLine $_.Row })
        $jobsByRepresentativeId = @{}
        foreach ($job in $batchJobs) {
            $jobsByRepresentativeId[[string]$job.Row.id] = $job
        }
        $payload = [ordered]@{
            batch_id = "$PassLabel-batch-$batchNumber"
            target_language = $TargetLanguage
            note = "Lines are in extracted file order. Translate source_template; use visible_source and metadata only as aid."
            translation_history = @($history)
            lines = $lines
        }

        $attempt = 0
        $validationHint = "none"
        $success = $false
        $lastRaw = ""
        $lastErrors = @()
        $currentLabel = if ($lines.Count -gt 0) { [string]$lines[0].file } else { $InputCsv }

        while (-not $success -and $attempt -le $MaxRetries) {
            $attempt += 1
            Write-TranslationProgress -Completed $script:completedTextRows -Total $script:totalTextRows -Status "$PassLabel batch $batchNumber/$($BatchSet.Count), lines=$($lines.Count), attempt=$attempt" -Label $currentLabel -BatchNumber $batchNumber -BatchTotal $BatchSet.Count
            $requestSeconds = 0.0
            $requestStartedAt = Get-Date
            try {
                $response = Invoke-MistralBatch -SystemPrompt $systemPrompt -BatchPayload $payload -ValidationHint $validationHint
                $requestSeconds = ((Get-Date) - $requestStartedAt).TotalSeconds
                $lastRaw = Get-ResponseContent $response
            } catch {
                $requestSeconds = ((Get-Date) - $requestStartedAt).TotalSeconds
                $lastRaw = ""
                $lastErrors = @("api request failed: $($_.Exception.Message)")
                $validationHint = ($lastErrors -join "; ")
                $delay = Get-RetryDelay -Attempt $attempt
                if ($attempt -le $MaxRetries -and $delay -gt 0) {
                    Wait-RetryWithProgress -Milliseconds $delay -Label $currentLabel -Status "API failed after $(Format-Duration $requestSeconds)" -BatchNumber $batchNumber -BatchTotal $BatchSet.Count
                } else {
                    Write-TranslationProgress -Completed $script:completedTextRows -Total $script:totalTextRows -Status "$PassLabel API failed" -Label $currentLabel -BatchNumber $batchNumber -BatchTotal $BatchSet.Count -LineStatus "API failed; no retries left"
                }
                continue
            }

            try {
                $parsed = $lastRaw | ConvertFrom-Json
            } catch {
                $lastErrors = @("response was not valid JSON: $($_.Exception.Message)")
                $validationHint = ($lastErrors -join "; ")
                Write-TranslationProgress -Completed $script:completedTextRows -Total $script:totalTextRows -Status "$PassLabel invalid JSON" -Label $currentLabel -BatchNumber $batchNumber -BatchTotal $BatchSet.Count -LineStatus "invalid JSON; retrying"
                continue
            }

            $translations = @($parsed.translations)
            $byId = @{}
            foreach ($translation in $translations) {
                if ($translation.id) {
                    $byId[[string]$translation.id] = $translation
                }
            }

            $errors = @()
            if ($translations.Count -ne $lines.Count) {
                $errors += "translation count mismatch: expected=$($lines.Count) got=$($translations.Count)"
            }
            $expectedIds = @{}
            foreach ($line in $lines) {
                $expectedIds[[string]$line.id] = $true
            }
            foreach ($translation in $translations) {
                if ($translation.id -and -not $expectedIds.ContainsKey([string]$translation.id)) {
                    $errors += "unexpected id $($translation.id)"
                }
            }
            foreach ($line in $lines) {
                if (-not $byId.ContainsKey([string]$line.id)) {
                    $errors += "missing id $($line.id)"
                    continue
                }
                $translation = $byId[[string]$line.id]
                $translatedText = [string]$translation.translation_template
                if ([string]::IsNullOrWhiteSpace($translatedText) -and -not [string]::IsNullOrWhiteSpace($line.source_template)) {
                    $errors += "empty translation for id $($line.id)"
                    continue
                }
                $reason = ""
                if (-not (Test-TranslationPlaceholders -Source $line.source_template -Translation $translatedText -Reason ([ref]$reason))) {
                    $errors += "id $($line.id): $reason"
                }
            }

            if ($errors.Count -eq 0) {
                $rowsWrittenThisBatch = 0
                foreach ($line in $lines) {
                    $translation = $byId[[string]$line.id]
                    $historyEntry = [ordered]@{
                        speaker = [string]$line.speaker
                        source_template = [string]$line.source_template
                        translation_template = [string]$translation.translation_template
                    }
                    [void]$history.Add($historyEntry)
                    while ($history.Count -gt $HistorySize) {
                        $history.RemoveAt(0)
                    }
                    $job = $jobsByRepresentativeId[[string]$line.id]
                    foreach ($aliasRow in @($job.Rows)) {
                        $aliasLine = Convert-RowToLine $aliasRow
                        if ($done.ContainsKey([string]$aliasLine.id)) {
                            continue
                        }
                        $entry = [ordered]@{
                            id = [string]$aliasLine.id
                            file = [string]$aliasLine.file
                            source = [string]$aliasLine.source
                            context = [string]$aliasLine.context
                            event = $aliasLine.event
                            speaker = [string]$aliasLine.speaker
                            speaker_translation = [string]$translation.speaker_translation
                            source_template = [string]$aliasLine.source_template
                            translation_template = [string]$translation.translation_template
                            tokens = $aliasLine.tokens
                            model = $Model
                            batch_id = [string]$payload.batch_id
                            representative_id = [string]$line.id
                            translated_at_utc = [DateTime]::UtcNow.ToString("o")
                            usage = $response.usage
                        }
                        Append-JsonLine -Path $OutputJsonl -Object $entry
                        $done[[string]$aliasLine.id] = $true
                        $script:completedTextRows += 1
                        $rowsWrittenThisBatch += 1
                    }
                }
                if ($rowsWrittenThisBatch -gt 0 -and $requestSeconds -gt 0) {
                    $script:apiRowsTotal += $rowsWrittenThisBatch
                    $script:apiSecondsTotal += $requestSeconds
                    $script:apiRequestCount += 1
                    $script:lastApiSeconds = $requestSeconds
                }
                $success = $true
                $avgRequestSeconds = if ($script:apiRequestCount -gt 0) { $script:apiSecondsTotal / $script:apiRequestCount } else { 0 }
                Write-TranslationProgress -Completed $script:completedTextRows -Total $script:totalTextRows -Status "$PassLabel translated batch $batchNumber" -Label $currentLabel -BatchNumber $batchNumber -BatchTotal $BatchSet.Count -LineStatus "done; last API $(Format-Duration $requestSeconds); avg API $(Format-Duration $avgRequestSeconds)" -NewLine
            } else {
                $lastErrors = $errors
                $validationHint = ($errors -join "; ")
                Write-TranslationProgress -Completed $script:completedTextRows -Total $script:totalTextRows -Status "$PassLabel validation retry" -Label $currentLabel -BatchNumber $batchNumber -BatchTotal $BatchSet.Count -LineStatus "validation failed; retrying"
            }
        }

        if (-not $success) {
            Complete-ConsoleProgressLine
            $failedEntry = [ordered]@{
                batch_id = [string]$payload.batch_id
                pass = $PassLabel
                errors = $lastErrors
                lines = $lines
                raw_response = $lastRaw
                failed_at_utc = [DateTime]::UtcNow.ToString("o")
            }
            Append-JsonLine -Path $FailedJsonl -Object $failedEntry
            Write-Warning "$PassLabel batch $batchNumber failed; wrote $FailedJsonl"
            if ($StopOnFailure) {
                throw "Stopping after failed $PassLabel batch $batchNumber"
            }
        }

        if ($SleepMs -gt 0) {
            Start-Sleep -Milliseconds $SleepMs
        }
    }
}

$pass = 1
Invoke-TranslationBatchSet -BatchSet $batches -PassLabel "pass-$pass"

while (-not $NoEndRetry -and $pass -le $EndRetryRounds) {
    $remainingRows = @($rows | Where-Object { -not $done.ContainsKey([string]$_.id) })
    if ($remainingRows.Count -eq 0) {
        break
    }

    $pass += 1
    $retryJobs = @(New-TranslationJobs -Rows $remainingRows -DisableDedupe:$NoDedupe)
    $retryBatches = @(New-Batches -Jobs $retryJobs -Size $BatchSize)
    Complete-ConsoleProgressLine
    Write-Warning "retry pass $pass starting for $($remainingRows.Count) untranslated rows in $($retryBatches.Count) batches"
    if ($RetryDelayMs -gt 0) {
        Start-Sleep -Milliseconds $RetryDelayMs
    }
    Invoke-TranslationBatchSet -BatchSet $retryBatches -PassLabel "pass-$pass"
}

$remainingRows = @($rows | Where-Object { -not $done.ContainsKey([string]$_.id) })
Complete-ConsoleProgressLine
if ($remainingRows.Count -gt 0) {
    Write-Warning "unfinished rows: $($remainingRows.Count). They remain absent from $OutputJsonl and will be retried first on the next run."
} else {
    Write-Host "all requested rows translated"
}
Write-Progress -Activity "Mistral translation" -Completed
Write-Host "done: $OutputJsonl"
