@echo off
setlocal EnableDelayedExpansion

echo ==========================================
echo    DazedMTLTool Startup Script
echo ==========================================
echo.

:: Check if Python is installed and get version
echo [1/4] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python 3.12 or higher from https://python.org
    pause
    exit /b 1
)

:: Get Python version and check if it's 3.12 or higher
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
for /f "tokens=1,2 delims=." %%a in ("%PYTHON_VERSION%") do (
    set MAJOR=%%a
    set MINOR=%%b
)

if !MAJOR! LSS 3 (
    echo ERROR: Python version !PYTHON_VERSION! is too old.
    echo Please install Python 3.12 or higher.
    pause
    exit /b 1
)

if !MAJOR! EQU 3 if !MINOR! LSS 12 (
    echo ERROR: Python version !PYTHON_VERSION! is too old.
    echo Please install Python 3.12 or higher.
    pause
    exit /b 1
)

echo ✓ Python !PYTHON_VERSION! detected (compatible)
echo.

:: Check if virtual environment exists
echo [2/4] Checking virtual environment...
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo ✓ Virtual environment created
) else (
    echo ✓ Virtual environment already exists
)
echo.

:: Activate virtual environment
echo [3/4] Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment.
    pause
    exit /b 1
)
echo ✓ Virtual environment activated
echo.

:: Check and install dependencies
echo [4/4] Checking dependencies...
echo Checking if requirements are satisfied...

:: Try importing key packages to see if they're installed
python -c "import PyQt5; import openai; import dotenv; import PIL; print('All dependencies satisfied')" >nul 2>&1
if errorlevel 1 (
    echo Installing/updating requirements...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install requirements.
        pause
        exit /b 1
    )
    echo ✓ Dependencies installed successfully
) else (
    echo ✓ All dependencies are already satisfied
)
echo.

:: Launch the GUI
echo ==========================================
echo    Launching DazedMTLTool GUI...
echo ==========================================
echo.

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
pause