@echo off
setlocal

REM Copy GAMEUPDATE.bat to a new file
copy "gameupdate\patch.bat" "gameupdate\patch2.bat"

REM Run the new file
call "gameupdate\patch2.bat"

REM Delete the new file
del "gameupdate\patch2.bat"

endlocal
@echo on