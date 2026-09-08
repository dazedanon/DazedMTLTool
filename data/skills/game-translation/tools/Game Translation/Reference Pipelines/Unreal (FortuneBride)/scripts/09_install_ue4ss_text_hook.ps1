param(
    [string]$GameRoot = "",
    [string]$ModSource = "",
    [string]$ModsDir = "",
    [switch]$Enable
)

$ErrorActionPreference = "Stop"
$toolRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (!$GameRoot) { $GameRoot = (Resolve-Path (Join-Path $toolRoot "..")).Path }
if (!$ModSource) { $ModSource = Join-Path $toolRoot "runtime_hook\IkisawTextHook" }

if (!$ModsDir) {
    $candidates = @(
        (Join-Path $GameRoot "StoryFramework\Binaries\Win64\ue4ss\Mods"),
        (Join-Path $GameRoot "StoryFramework\Binaries\Win64\Mods")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            $ModsDir = $candidate
            break
        }
    }
}

if (!$ModsDir) {
    throw "No UE4SS Mods folder was found. Install UE4SS first, or pass -ModsDir explicitly."
}
if (!(Test-Path $ModSource)) { throw "Missing mod source at $ModSource" }

$dest = Join-Path $ModsDir "IkisawTextHook"
if (Test-Path $dest) {
    Get-ChildItem -LiteralPath $ModSource -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $dest -Recurse -Force
    }
} else {
    Copy-Item -LiteralPath $ModSource -Destination $ModsDir -Recurse -Force
}

$enabledMarker = Join-Path $dest "enabled.txt"
$disabledMarker = Join-Path $dest "enabled.txt.disabled"
if ($Enable) {
    if (Test-Path $disabledMarker) {
        Move-Item -LiteralPath $disabledMarker -Destination $enabledMarker -Force
    } elseif (!(Test-Path $enabledMarker)) {
        Set-Content -Path $enabledMarker -Encoding ASCII -Value ""
    }
} elseif (Test-Path $enabledMarker) {
    Move-Item -LiteralPath $enabledMarker -Destination $disabledMarker -Force
}

$modsTxt = Join-Path $ModsDir "mods.txt"
if (Test-Path $modsTxt) {
    $lines = @(Get-Content -Path $modsTxt | Where-Object { $_ -notmatch "^\s*IkisawTextHook\s*:" })
    $state = if ($Enable) { "1" } else { "0" }
    $insertAt = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "Built-in keybinds" -or $lines[$i] -match "^\s*Keybinds\s*:") {
            $insertAt = $i
            break
        }
    }
    if ($insertAt -ge 0) {
        $updated = @()
        if ($insertAt -gt 0) { $updated += $lines[0..($insertAt - 1)] }
        $updated += "IkisawTextHook : $state"
        $updated += $lines[$insertAt..($lines.Count - 1)]
        Set-Content -Path $modsTxt -Encoding ASCII -Value $updated
    } else {
        Add-Content -Path $modsTxt -Value "IkisawTextHook : $state"
    }
}

Write-Host "Installed IkisawTextHook to $dest"
Write-Host "IkisawTextHook mods.txt state: $(if ($Enable) { 'enabled' } else { 'disabled' })"
