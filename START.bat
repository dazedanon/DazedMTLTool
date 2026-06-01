@echo off
setlocal EnableDelayedExpansion

echo ==========================================
echo    DazedMTLTool Startup Script
echo ==========================================
echo.

:: Track whether we actually need to create a new venv
set "NEED_VENV_CREATE=0"

:: Determine which venv directory to use (.venv or venv)
set "VENV_DIR="
if exist ".venv" set "VENV_DIR=.venv"
if not defined VENV_DIR if exist "venv" set "VENV_DIR=venv"
set "CREATE_VENV_DIR="


:: Step 1: Check if a virtual environment exists (.venv or venv)
echo [1/4] Checking for a virtual environment...
if defined VENV_DIR (
    echo !VENV_DIR! found. Checking its Python version...
    if not exist "!VENV_DIR!\Scripts\python.exe" (
        echo ERROR: Python executable not found at "!VENV_DIR!\Scripts\python.exe".
        set "CREATE_VENV_DIR=!VENV_DIR!"
        call :BackupVenv "!VENV_DIR!"
        set "NEED_VENV_CREATE=1"
    ) else (
        for /f "tokens=2" %%i in ('"!VENV_DIR!\Scripts\python.exe" --version 2^>^&1') do set VENV_PYTHON_VERSION=%%i
        if not defined VENV_PYTHON_VERSION (
            echo ERROR: Could not determine Python version from "!VENV_DIR!\Scripts\python.exe".
            set "CREATE_VENV_DIR=!VENV_DIR!"
            call :BackupVenv "!VENV_DIR!"
            set "NEED_VENV_CREATE=1"
        ) else (
            echo Detected Python version: !VENV_PYTHON_VERSION!
            for /f "tokens=1,2 delims=." %%a in ("!VENV_PYTHON_VERSION!") do (
                set VENV_MAJOR=%%a
                set VENV_MINOR=%%b
            )
            if !VENV_MAJOR! EQU 3 if !VENV_MINOR! GEQ 12 if !VENV_MINOR! LSS 15 (
                echo !VENV_DIR! Python version !VENV_PYTHON_VERSION! is compatible ^(^>^=3.12 and ^<3.15^).
                goto :activate_venv
            ) else (
                echo !VENV_DIR! Python version !VENV_PYTHON_VERSION! is not supported ^(requires ^>^=3.12 and ^<3.15^)
                echo Backing up !VENV_DIR!...
                set "CREATE_VENV_DIR=!VENV_DIR!"
                call :BackupVenv "!VENV_DIR!"
                set "NEED_VENV_CREATE=1"
            )
        )
    )
) else (
    echo No existing virtual environment found.
    set "CREATE_VENV_DIR=.venv"
    set "NEED_VENV_CREATE=1"
)
echo.

:: If we don't need to create a new venv, skip straight to activation
if "%NEED_VENV_CREATE%"=="0" goto :activate_venv

:: Step 2: Find suitable global Python and create a virtual environment

set "FOUND_PYTHON="
for /f "delims=" %%p in ('where python 2^>nul') do (
    call :CheckPythonVersion "%%p"
)

:: Fallback: try 'python' directly if 'where' found nothing (handles Windows Store alias)
if not defined FOUND_PYTHON (
    python --version >nul 2>&1
    if not errorlevel 1 (
        call :CheckPythonVersion "python"
    )
)

if not defined FOUND_PYTHON (
    echo ERROR: No suitable Python ^(>=3.12 and <3.15^) found in PATH.
    echo Please install Python 3.12, 3.13, or 3.14 and ensure it is in your PATH.
    pause
    exit /b 1
)

:create_venv
if not defined CREATE_VENV_DIR set "CREATE_VENV_DIR=.venv"
echo Creating new !CREATE_VENV_DIR! using !FOUND_PYTHON! ...
"!FOUND_PYTHON!" -m venv !CREATE_VENV_DIR!
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)
echo Virtual environment created
echo.

:: Proceed to activation after creating the venv to avoid falling through into subroutines
set "VENV_DIR=!CREATE_VENV_DIR!"
goto :activate_venv

:CheckPythonVersion
rem -- %1 is the python executable path
rem -- Skip if we already found a suitable Python
if defined FOUND_PYTHON goto :eof
set "PYTHON_VERSION="
set "MAJOR="
set "MINOR="
for /f "tokens=2" %%i in ('"%~1" --version 2^>nul') do set PYTHON_VERSION=%%i
if not defined PYTHON_VERSION goto :eof
for /f "tokens=1,2 delims=." %%a in ("%PYTHON_VERSION%") do (
    set MAJOR=%%a
    set MINOR=%%b
)
if not defined MAJOR goto :eof
if not defined MINOR goto :eof
if !MAJOR! EQU 3 if !MINOR! GEQ 12 if !MINOR! LSS 15 (
    set "FOUND_PYTHON=%~1"
)
goto :eof

:activate_venv
echo Activating virtual environment...
call !VENV_DIR!\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment at "!VENV_DIR!".
    echo Attempting to recreate the virtual environment with a compatible Python...
    set "CREATE_VENV_DIR=!VENV_DIR!"
    call :BackupVenv "!VENV_DIR!"
    set "FOUND_PYTHON="
    for /f "delims=" %%p in ('where python') do (
        call :CheckPythonVersion "%%p"
    )
    if not defined FOUND_PYTHON (
        echo ERROR: No suitable Python ^(^>^=3.12 and ^<3.15^) found in PATH for recreation.
        pause
        exit /b 1
    )
    echo Recreating !CREATE_VENV_DIR! using !FOUND_PYTHON! ...
    "!FOUND_PYTHON!" -m venv !CREATE_VENV_DIR!
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment during recreation.
        pause
        exit /b 1
    )
    set "VENV_DIR=!CREATE_VENV_DIR!"
    echo Retrying activation...
    call !VENV_DIR!\Scripts\activate.bat
    if errorlevel 1 (
        echo ERROR: Activation failed after recreation.
        pause
        exit /b 1
    )
)
echo Virtual environment activated
echo.

:: (proceeding to dependency checks and launch)

:: Check and install dependencies
echo Checking dependencies...
echo Checking if requirements are satisfied...

:: Try importing key packages to see if they're installed
python -c "import PyQt5; import openai; import dotenv; import PIL; import anthropic; print('All dependencies satisfied')" >nul 2>&1
if errorlevel 1 (
    echo Upgrading pip...
    python -m pip install --upgrade pip >nul 2>&1
    echo Installing/updating requirements...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install requirements.
        pause
        exit /b 1
    )
    echo Dependencies installed successfully
) else (
    echo All dependencies are already satisfied
)
echo.

:: Launch the GUI
echo ==========================================
echo    Launching DazedMTLTool GUI...
echo ==========================================
echo.

:: Ensure vocab.txt exists (create from example if available)
if not exist "vocab.txt" (
    if exist "vocab.txt.example" (
        echo vocab.txt not found - creating from vocab.txt.example...
        copy /Y "vocab.txt.example" "vocab.txt" >nul 2>&1
        if errorlevel 1 (
            echo ERROR: Failed to copy vocab.txt.example to vocab.txt.
        ) else (
            echo Created vocab.txt from vocab.txt.example
        )
    ) else (
        echo vocab.txt and vocab.txt.example not found - creating empty vocab.txt to avoid import errors...
        type NUL > "vocab.txt"
        if errorlevel 1 (
            echo ERROR: Failed to create empty vocab.txt.
        ) else (
            echo Created empty vocab.txt
        )
    )
)

python start_gui.py

:: Check if GUI launched successfully
if errorlevel 1 (
    echo.
    echo ERROR: Failed to launch GUI.
    echo Check the error messages above.
    pause
    exit /b 1
)

echo.
echo GUI closed successfully.

:: End of main flow - prevent falling through into subroutines below
goto :eof

:: Backup venv subroutine (supports .venv or venv)
:BackupVenv
set "TARGET_DIR=%~1"
if not defined TARGET_DIR set "TARGET_DIR=.venv"
set BAK_IDX=1
:BackupLoop
if exist "%TARGET_DIR%.bak_!BAK_IDX!" (
    set /a BAK_IDX+=1
    goto BackupLoop
)
move /Y "%TARGET_DIR%" "%TARGET_DIR%.bak_!BAK_IDX!" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Failed to back up %TARGET_DIR% to %TARGET_DIR%.bak_!BAK_IDX!.
    echo Please ensure no files are locked and try again.
    goto :eof
)
echo %TARGET_DIR% renamed to %TARGET_DIR%.bak_!BAK_IDX!
goto :eof