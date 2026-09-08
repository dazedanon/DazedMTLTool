param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$Config = (Join-Path $PSScriptRoot "..\config.json")
)

$ErrorActionPreference = "Stop"
$cfg = Get-Content -Raw -Path $Config | ConvertFrom-Json
$work = Join-Path (Split-Path $Config -Parent) "work"
New-Item -ItemType Directory -Force -Path $work | Out-Null

$manifest = Join-Path $Root "Manifest_UFSFiles_Win64.txt"
if (!(Test-Path $manifest)) {
    throw "Manifest_UFSFiles_Win64.txt was not found at $Root"
}

$patterns = @($cfg.targetPathPatterns)
$rows = Get-Content -Path $manifest | ForEach-Object {
    $path = ($_ -split "`t")[0] -replace "\\", "/"
    foreach ($pattern in $patterns) {
        if ($path.StartsWith($pattern, [System.StringComparison]::OrdinalIgnoreCase) -and
            ($path.EndsWith(".uasset") -or $path.EndsWith(".umap") -or $path.EndsWith(".uexp") -or $path.EndsWith(".ubulk"))) {
            [PSCustomObject]@{
                path = $path
                extension = [System.IO.Path]::GetExtension($path).TrimStart(".")
                group = $pattern
            }
            break
        }
    }
}

$rows = @($rows | Sort-Object path -Unique)
$assetPaths = @($rows | Where-Object { $_.extension -eq "uasset" -or $_.extension -eq "umap" } | ForEach-Object { $_.path })
$assetRoots = @($assetPaths | ForEach-Object { $_ -replace "\.(uasset|umap)$", "" })

$rows | Export-Csv -NoTypeInformation -Encoding UTF8 -Path (Join-Path $work "candidate-files.csv")
$assetPaths | Set-Content -Encoding UTF8 -Path (Join-Path $work "candidate-assets.txt")
$assetRoots | Set-Content -Encoding UTF8 -Path (Join-Path $work "candidate-asset-roots.txt")

$summary = [PSCustomObject]@{
    root = $Root
    paksDir = (Join-Path $Root $cfg.paksDir)
    candidateFiles = $rows.Count
    candidateAssets = $assetPaths.Count
    groups = @($rows | Group-Object group | ForEach-Object {
        [PSCustomObject]@{ group = $_.Name; files = $_.Count }
    })
}

$summary | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 -Path (Join-Path $work "inventory-summary.json")
$summary | ConvertTo-Json -Depth 4
