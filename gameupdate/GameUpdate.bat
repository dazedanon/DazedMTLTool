@echo off
setlocal

REM Copy patch.bat to a temp name so the live patch.bat can be overwritten during updates
copy /Y "gameupdate\patch.bat" "gameupdate\patch2.bat" >nul
call "gameupdate\patch2.bat"
del /Q "gameupdate\patch2.bat" >nul 2>&1

endlocal