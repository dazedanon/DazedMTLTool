@echo off
set /p choice=Do you want to edit the .env file? (y/n):
if /i "%choice%"=="y" (
    notepad .env
    echo Press enter when you are done
    pause
    echo Continuing...
) else (
    echo Continuing without editing .env file...
)
python3 -m pip install -r requirements.txt
python3 start.py
pause