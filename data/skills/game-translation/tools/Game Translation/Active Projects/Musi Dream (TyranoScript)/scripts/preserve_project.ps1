$ErrorActionPreference = 'Stop'
$projectSource = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$projectDestination = 'C:\Users\sw\Desktop\Tools\Game Translation\Active Projects\Musi Dream (TyranoScript)'
if (Test-Path -LiteralPath $projectDestination) {
    throw "Destination already exists; refusing to overwrite: $projectDestination"
}
$allowedDirectories = @('scripts', 'source', 'store', 'packets', 'prompts')
$allowedFiles = @('tl.py', 'README.md', 'glossary.json', 'game_bible.md', 'quirks.md', 'VALIDATION_PLAN.md', 'PROVENANCE.md')
$toCopy = [Collections.Generic.List[IO.FileInfo]]::new()
foreach ($name in $allowedFiles) {
    $toCopy.Add((Get-Item -LiteralPath (Join-Path $projectSource $name)))
}
foreach ($name in $allowedDirectories) {
    foreach ($file in (Get-ChildItem -LiteralPath (Join-Path $projectSource $name) -File -Recurse)) {
        if ($file.FullName -notmatch '[\\/]__pycache__[\\/]' -and $file.Extension -ne '.pyc') {
            $toCopy.Add($file)
        }
    }
}
# Keep evidence reports; omit temporary no-op builds and import-test stores.
foreach ($file in (Get-ChildItem -LiteralPath (Join-Path $projectSource 'reports') -File)) {
    $toCopy.Add($file)
}
New-Item -ItemType Directory -Path $projectDestination | Out-Null
$count = 0
foreach ($file in $toCopy) {
    $relative = $file.FullName.Substring($projectSource.Length + 1)
    $target = [IO.Path]::GetFullPath((Join-Path $projectDestination $relative))
    if (-not $target.StartsWith($projectDestination + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Target escapes destination: $target"
    }
    New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($target)) -Force | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $target
    if ((Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash -ne
        (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash) {
        throw "Copied file mismatch: $relative"
    }
    $count++
}
Write-Output "Verified $count files in $projectDestination"
