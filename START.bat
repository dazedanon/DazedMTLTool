@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_desktop.ps1" %*
if errorlevel 1 (
    echo.
    echo Setup did not finish. Your existing files were retained.
    pause
    exit /b 1
)
