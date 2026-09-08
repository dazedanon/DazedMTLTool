<#
  Dress Quest - English patch installer.

  RPG Maker VX Ace serves Data\*.rvdata2 out of Game.rgss3a whenever that
  archive is present, and IGNORES a loose file of the same name. So dropping
  the patch in next to the archive does nothing at all - the game just starts
  in Japanese. The archive has to come out of the way first, which means its
  contents have to be extracted, which is what this script is for.

  What it does:
    1. reads Game.rgss3a and writes out everything inside it (Data\, Graphics\)
    2. copies this patch's Data\ over the extracted one
    3. renames Game.rgss3a to Game.rgss3a.original

  Nothing is deleted. -Uninstall puts it all back.

  The extraction runs through a small embedded C# class because the archive is
  95 MB of XOR-ed bytes and a PowerShell byte loop would take minutes.
#>
[CmdletBinding()]
param(
    [string]$GameDir = "",
    [switch]$Uninstall,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Say($msg)  { Write-Host "  $msg" }
function Good($msg) { Write-Host "  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  $msg" -ForegroundColor Yellow }
function Die($msg)  { Write-Host ""; Write-Host "  $msg" -ForegroundColor Red; Write-Host ""; exit 1 }

# --------------------------------------------------------------------------
# find the game
# --------------------------------------------------------------------------
function Find-GameDir {
    param([string]$Hint)
    $candidates = @()
    if ($Hint) { $candidates += $Hint }
    $candidates += $here                      # patch unzipped into the game folder
    $candidates += (Split-Path -Parent $here) # ...or into a subfolder of it
    foreach ($c in $candidates) {
        if (-not $c) { continue }
        if ((Test-Path (Join-Path $c "Game.exe")) -and
            ((Test-Path (Join-Path $c "Game.rgss3a")) -or
             (Test-Path (Join-Path $c "Game.rgss3a.original")) -or
             (Test-Path (Join-Path $c "Data")))) {
            return (Resolve-Path $c).Path
        }
    }
    return $null
}

# --------------------------------------------------------------------------
# the RGSSAD v3 reader, in C# so it runs at native speed
# --------------------------------------------------------------------------
$rgssad = @'
using System;
using System.IO;

public static class Rgssad {
    // Header: "RGSSAD\0\3", then a u32 seed. The table key is seed*9+3; every
    // field in the entry table is XOR-ed with it, and each file's payload is
    // XOR-ed with its own key, advancing k = k*7+3 after every 4 bytes.
    public static int Extract(string archive, string outDir) {
        byte[] a = File.ReadAllBytes(archive);
        if (a.Length < 12 || a[0] != 'R' || a[1] != 'G' || a[2] != 'S' ||
            a[3] != 'S' || a[4] != 'A' || a[5] != 'D' || a[6] != 0)
            throw new Exception("not an RGSSAD archive");
        if (a[7] != 3)
            throw new Exception("unsupported RGSSAD version " + a[7]);

        int pos = 8;
        uint key = unchecked(U32(a, ref pos) * 9 + 3);
        byte[] kb = BitConverter.GetBytes(key);
        int count = 0;

        while (pos + 16 <= a.Length) {
            uint offset = U32(a, ref pos) ^ key;
            uint size   = U32(a, ref pos) ^ key;
            uint dkey   = U32(a, ref pos) ^ key;
            uint nlen   = U32(a, ref pos) ^ key;
            if (offset == 0) break;
            if (nlen > 4096 || pos + nlen > a.Length)
                throw new Exception("corrupt entry table");

            byte[] nb = new byte[nlen];
            for (int i = 0; i < nlen; i++) nb[i] = (byte)(a[pos + i] ^ kb[i % 4]);
            pos += (int)nlen;
            string name = System.Text.Encoding.UTF8.GetString(nb).Replace('\\', '/');

            string dest = Path.Combine(outDir, name.Replace('/', Path.DirectorySeparatorChar));
            string full = Path.GetFullPath(dest);
            if (!full.StartsWith(Path.GetFullPath(outDir) + Path.DirectorySeparatorChar))
                throw new Exception("entry escapes the output directory: " + name);
            Directory.CreateDirectory(Path.GetDirectoryName(full));

            byte[] data = new byte[size];
            Array.Copy(a, (int)offset, data, 0, (int)size);
            uint k = dkey;
            for (int i = 0; i < data.Length; i += 4) {
                byte[] cur = BitConverter.GetBytes(k);
                for (int j = 0; j < 4 && i + j < data.Length; j++) data[i + j] ^= cur[j];
                k = unchecked(k * 7 + 3);
            }
            File.WriteAllBytes(full, data);
            count++;
        }
        return count;
    }

    private static uint U32(byte[] a, ref int pos) {
        uint v = (uint)(a[pos] | (a[pos+1] << 8) | (a[pos+2] << 16) | (a[pos+3] << 24));
        pos += 4;
        return v;
    }
}
'@

# --------------------------------------------------------------------------
Write-Host ""
Write-Host "  Dress Quest - English patch" -ForegroundColor Cyan
Write-Host ""

$game = Find-GameDir -Hint $GameDir
if (-not $game) {
    Die ("Could not find the game. Put this folder inside your Dress Quest " +
         "folder (the one with Game.exe) and run it again, or call it with " +
         "-GameDir `"C:\path\to\Dress Quest`".")
}
Say "game folder : $game"

$archive  = Join-Path $game "Game.rgss3a"
$stashed  = Join-Path $game "Game.rgss3a.original"
$dataDir  = Join-Path $game "Data"

# --------------------------------------------------------------------------
if ($Uninstall) {
    if (-not (Test-Path $stashed)) {
        Die "Game.rgss3a.original is not there, so this patch is not installed."
    }
    if (Test-Path $archive) { Remove-Item $archive -Force }
    Rename-Item $stashed "Game.rgss3a"
    foreach ($d in @("Data", "Graphics")) {
        $p = Join-Path $game $d
        if (Test-Path $p) { Remove-Item $p -Recurse -Force; Say "removed $d\" }
    }
    Good "reverted - the game is Japanese again, straight out of the archive."
    Write-Host ""
    exit 0
}

# --------------------------------------------------------------------------
$patchData = Join-Path $here "Patch\Data"
if (-not (Test-Path $patchData)) { Die "Patch\Data is missing next to this script." }
$patchCount = (Get-ChildItem $patchData -Filter *.rvdata2).Count
Say "patch files : $patchCount"

if ((Test-Path $stashed) -and -not $Force) {
    Warn "this game is already patched (Game.rgss3a.original exists)."
    Warn "re-copying the patch files only. Use -Force to extract again."
} elseif (Test-Path $archive) {
    Say "extracting Game.rgss3a - this takes a few seconds..."
    Add-Type -TypeDefinition $rgssad -Language CSharp
    $n = [Rgssad]::Extract($archive, $game)
    Good "extracted $n file(s) into Data\ and Graphics\"
} elseif (Test-Path $dataDir) {
    Warn "no archive found, but Data\ exists - patching the loose files."
} else {
    Die "No Game.rgss3a and no Data\ folder. Is this really the game folder?"
}

Copy-Item (Join-Path $patchData "*.rvdata2") $dataDir -Force
Good "copied $patchCount translated file(s) into Data\"

if (Test-Path $archive) {
    Move-Item $archive $stashed -Force
    Good "moved Game.rgss3a aside (kept as Game.rgss3a.original)"
}

Write-Host ""
Good "done - run Game.exe."
Say  "to undo:  install.bat uninstall"
Write-Host ""
