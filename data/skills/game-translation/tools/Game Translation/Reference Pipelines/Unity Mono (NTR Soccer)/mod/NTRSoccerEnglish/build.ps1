# Builds NTRSoccerEnglish.dll against the game's own assemblies and installs
# it (plus the translation dictionary) into BepInEx/plugins/NTRSoccerEnglish/.
$ErrorActionPreference = "Stop"

$modDir  = $PSScriptRoot
$gameDir = (Get-Item $modDir).Parent.Parent.Parent.FullName   # ...\NTR Soccer
$managed = Join-Path $gameDir "NTR_Soccer_Data\Managed"
$core    = Join-Path $gameDir "BepInEx\core"
$outDir  = Join-Path $gameDir "BepInEx\plugins\NTRSoccerEnglish"
$tools   = Join-Path $gameDir "tools"

$csc = "C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\Roslyn\csc.exe"
if (-not (Test-Path $csc)) { throw "csc.exe not found: $csc" }

New-Item -ItemType Directory -Force $outDir | Out-Null
New-Item -ItemType Directory -Force (Join-Path $outDir "translations") | Out-Null

$refs = @(
    (Join-Path $managed "mscorlib.dll"),
    (Join-Path $managed "netstandard.dll"),
    (Join-Path $managed "System.dll"),
    (Join-Path $managed "System.Core.dll"),
    (Join-Path $managed "UnityEngine.dll"),
    (Join-Path $managed "UnityEngine.CoreModule.dll"),
    (Join-Path $managed "UnityEngine.TextRenderingModule.dll"),
    (Join-Path $managed "UnityEngine.UI.dll"),
    (Join-Path $managed "Unity.TextMeshPro.dll"),
    (Join-Path $managed "Assembly-CSharp-firstpass.dll"),
    (Join-Path $core "BepInEx.dll"),
    (Join-Path $core "0Harmony.dll")
) | ForEach-Object { "/r:`"$_`"" }

$sources = Get-ChildItem $modDir -Filter *.cs | ForEach-Object { "`"$($_.FullName)`"" }

$dll = Join-Path $outDir "NTRSoccerEnglish.dll"
& $csc /nologo /noconfig /nostdlib+ /target:library /optimize+ /langversion:latest `
    /out:"$dll" @refs @sources
if ($LASTEXITCODE -ne 0) { throw "csc failed with exit code $LASTEXITCODE" }

Copy-Item (Join-Path $tools "translated\translations_final.json") `
          (Join-Path $outDir "translations\translations_final.json") -Force

Write-Host "built  : $dll"
Write-Host "dict   : $outDir\translations\translations_final.json"
