# Compile the C caves to position-independent shellcode (load_table.bin = P5b folder
# reader, apply_fontsize.bin = P8 fontSize override). Only needed if you change the .c;
# patch_exe.py uses the committed .bin files.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
$vs = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat"

cmd /c "`"$vs`" >nul 2>&1 && cl /nologo /c /TC /O1 /GS- /Gs1000000 /Zl load_table.c /Foload_table.obj"
if ($LASTEXITCODE -ne 0) { Write-Error "cl failed (load_table)" }
python "$here\_emit.py"
Remove-Item "$here\load_table.obj" -ErrorAction SilentlyContinue

cmd /c "`"$vs`" >nul 2>&1 && cl /nologo /c /TC /O1 /GS- /Gs1000000 /Zl apply_fontsize.c /Foapply_fontsize.obj"
if ($LASTEXITCODE -ne 0) { Write-Error "cl failed (apply_fontsize)" }
python "$here\_emit2.py" apply_fontsize.obj apply_fontsize apply_fontsize.bin
Remove-Item "$here\apply_fontsize.obj" -ErrorAction SilentlyContinue

cmd /c "`"$vs`" >nul 2>&1 && cl /nologo /c /TC /O1 /GS- /Gs1000000 /Zl apply_title.c /Foapply_title.obj"
if ($LASTEXITCODE -ne 0) { Write-Error "cl failed (apply_title)" }
python "$here\_emit2.py" apply_title.obj resolve_title apply_title.bin
Remove-Item "$here\apply_title.obj" -ErrorAction SilentlyContinue
