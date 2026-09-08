@echo off
rem Double-click wrapper for install.ps1.
rem
rem `-ExecutionPolicy Bypass` applies to this one process only - it does not
rem change any machine setting - and it is what lets a downloaded .ps1 run
rem without the player editing policy first.
rem
rem   install.bat              install
rem   install.bat uninstall    put the original archive back

setlocal
set ACTION=
if /I "%~1"=="uninstall" set ACTION=-Uninstall

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %ACTION% %2 %3
if errorlevel 1 (
  echo.
  echo   Something went wrong - read the message above.
)
echo.
pause
