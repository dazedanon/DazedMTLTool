$ErrorActionPreference = 'Stop'
$projectSource = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$gameSource = [IO.Path]::GetFullPath((Join-Path $projectSource '..'))
$projectTarget = 'C:\Users\sw\Desktop\Tools\Game Translation\Active Projects\Yume Yoshiwara (TyranoScript)'
$allowedTarget = [IO.Path]::GetFullPath('C:\Users\sw\Desktop\Tools\Game Translation\Active Projects')
if (-not [IO.Path]::GetFullPath($projectTarget).StartsWith($allowedTarget + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid preservation target' }
New-Item -ItemType Directory -Path $projectTarget -Force | Out-Null
& robocopy $projectSource $projectTarget /E /XD qa __pycache__ /R:1 /W:1 /NFL /NDL /NJH /NJS
if ($LASTEXITCODE -ge 8) { throw "Project copy failed: $LASTEXITCODE" }
& robocopy (Join-Path $gameSource 'images_for_review') (Join-Path $projectTarget 'images_for_review') /E /R:1 /W:1 /NFL /NDL /NJH /NJS
if ($LASTEXITCODE -ge 8) { throw "Image copy failed: $LASTEXITCODE" }
$sourceCatalog = (Get-FileHash -LiteralPath (Join-Path $projectSource 'catalog.json') -Algorithm SHA256).Hash
$targetCatalog = (Get-FileHash -LiteralPath (Join-Path $projectTarget 'catalog.json') -Algorithm SHA256).Hash
if ($sourceCatalog -ne $targetCatalog) { throw 'Preserved catalog hash differs' }
Write-Output "Preserved project: $projectTarget"
exit 0
