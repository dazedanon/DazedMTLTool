# Builds CoinPussyEnglish.dll against the game's own assemblies and installs it,
# with the translation payload, into BepInEx/plugins/CoinPussyEnglish/.
#
#   .\build.ps1              build + install
#   .\build.ps1 -NoPackage   build only, leave the existing payload alone
param([switch]$NoPackage)

$ErrorActionPreference = "Stop"

$modDir  = $PSScriptRoot
$gameDir = (Get-Item $modDir).Parent.Parent.Parent.FullName      # ...\CoinPussy
$managed = Join-Path $gameDir "CoinPussy_Data\Managed"
$core    = Join-Path $gameDir "BepInEx\core"
$outDir  = Join-Path $gameDir "BepInEx\plugins\CoinPussyEnglish"
$tools   = Join-Path $gameDir "tools"
$payload = Join-Path $tools "translated\plugin\translations"

foreach ($p in @($managed, $core)) {
    if (-not (Test-Path $p)) { throw "not found: $p" }
}

$csc = "C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\Roslyn\csc.exe"
if (-not (Test-Path $csc)) {
    $csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
}
if (-not (Test-Path $csc)) { throw "no C# compiler found" }

New-Item -ItemType Directory -Force $outDir | Out-Null

$refs = @(
    (Join-Path $managed "mscorlib.dll"),
    (Join-Path $managed "netstandard.dll"),
    (Join-Path $managed "System.dll"),
    (Join-Path $managed "System.Core.dll"),
    (Join-Path $managed "UnityEngine.dll"),
    (Join-Path $managed "UnityEngine.CoreModule.dll"),
    (Join-Path $managed "UnityEngine.TextRenderingModule.dll"),
    (Join-Path $managed "UnityEngine.UI.dll"),
    (Join-Path $managed "UnityEngine.UIModule.dll"),
    (Join-Path $managed "Unity.TextMeshPro.dll"),
    (Join-Path $core "BepInEx.dll"),
    (Join-Path $core "0Harmony.dll")
) | ForEach-Object {
    if (-not (Test-Path $_)) { throw "reference assembly missing: $_" }
    "/r:`"$_`""
}

# Assembly-CSharp is NOT referenced: CsvReader is resolved by name at runtime
# through AccessTools, so the plugin keeps building even if the game updates.

$sources = Get-ChildItem $modDir -Filter *.cs | ForEach-Object { "`"$($_.FullName)`"" }

$dll = Join-Path $outDir "CoinPussyEnglish.dll"
& $csc /nologo /noconfig /nostdlib+ /target:library /optimize+ /langversion:latest `
    /out:"$dll" @refs @sources
if ($LASTEXITCODE -ne 0) { throw "csc failed with exit code $LASTEXITCODE" }

if (-not $NoPackage) {
    if (-not (Test-Path $payload)) {
        Write-Warning "no payload at $payload - run: python tools\tl.py package"
    } else {
        $dest = Join-Path $outDir "translations"
        if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
        Copy-Item -Recurse $payload $dest
        $n = (Get-ChildItem (Join-Path $dest "csv") -Filter *.csv -ErrorAction SilentlyContinue).Count
        Write-Host "payload: $dest ($n CSVs)"
    }
}

Write-Host "built  : $dll"
Write-Host "run the game, then check BepInEx\LogOutput.log"
