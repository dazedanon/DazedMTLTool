@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM When deployed on a game: this file sits in the game root; patch scripts live in .\gameupdate\
REM In this repo the same layout is kept for neatness: this bat is under DazedMTLTool\gameupdate\ next to a nested gameupdate\ folder with patch.ps1.
set "GU_ROOT=%~dp0"
REM Game root is this batch file's folder (not %%CD%%, so full-path launches still work).
set "GAME_ROOT=!GU_ROOT!"
if "!GAME_ROOT:~-1!"=="\" set "GAME_ROOT=!GAME_ROOT:~0,-1!"
set "PATCH_SCRIPT_DIR=!GU_ROOT!gameupdate"

if not exist "!PATCH_SCRIPT_DIR!\patch.ps1" (
    echo ERROR: patch.ps1 not found at:
    echo   !PATCH_SCRIPT_DIR!\patch.ps1
    echo Expected layout: GameUpdate.bat and a gameupdate folder next to each other ^(same parent^).
    pause
    exit /b 1
)

REM Copy patch.ps1 so the live script can be overwritten during updates
copy /Y "!PATCH_SCRIPT_DIR!\patch.ps1" "!PATCH_SCRIPT_DIR!\patch2.ps1" >nul
if errorlevel 1 (
    echo ERROR: Could not copy patch.ps1 to patch2.ps1 in:
    echo   !PATCH_SCRIPT_DIR!
    pause
    exit /b 1
)

set "_my_shell=pwsh"
where /q !_my_shell!
if !errorlevel! neq 0 (
    echo PowerShell 7 ^(pwsh^) not found.
    if /I "%GAMEUPDATE_PROMPT_PWSH%"=="1" (
        echo.
        set /p "INSTALL_PWSH=PowerShell 7 is faster. Install now via winget? (Y/N): "
        if /I "!INSTALL_PWSH!"=="Y" (
            echo Installing PowerShell 7 via winget...
            winget install --id Microsoft.PowerShell --source winget --accept-package-agreements --accept-source-agreements
            where /q pwsh
            if !errorlevel! equ 0 (
                set "_my_shell=pwsh"
                echo PowerShell 7 installed; using pwsh.
            ) else (
                echo Install failed or unavailable; falling back to powershell.
                set "_my_shell=powershell"
            )
        ) else (
            echo Skipping install; falling back to powershell.
            set "_my_shell=powershell"
        )
    ) else (
        echo Tip: Set GAMEUPDATE_PROMPT_PWSH=1 to offer PowerShell 7 install.
        echo Falling back to powershell...
        set "_my_shell=powershell"
    )
    where /q !_my_shell!
    if !errorlevel! neq 0 (
        echo ERROR: Neither pwsh nor powershell was found.
        del /Q "!PATCH_SCRIPT_DIR!\patch2.ps1" >nul 2>&1
        pause
        exit /b 1
    )
)

!_my_shell! -NoProfile -ExecutionPolicy Bypass -File "!PATCH_SCRIPT_DIR!\patch2.ps1" -GameRoot "!GAME_ROOT!"
set "GU_PATCH_EXIT=!errorlevel!"
del /Q "!PATCH_SCRIPT_DIR!\patch2.ps1" >nul 2>&1

exit /b !GU_PATCH_EXIT!
