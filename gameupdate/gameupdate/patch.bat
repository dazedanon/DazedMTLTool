@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Check if being run from gameupdate folder (incorrect usage)
for %%I in ("%CD%") do set "CURRENT_FOLDER=%%~nxI"
if /I "%CURRENT_FOLDER%"=="gameupdate" (
    echo.
    echo ========================================
    echo ERROR: Do not run patch.bat directly!
    echo ========================================
    echo.
    echo You are running this from the gameupdate folder.
    echo This will not work correctly!
    echo.
    echo Please go back to the game's root folder and
    echo run GameUpdate.bat instead.
    echo ========================================
    echo.
    pause
    exit /b 1
)

REM Determine important paths
set "SCRIPT_DIR=%~dp0"
set "ROOT_DIR=%CD%"
set "CONFIG_FILE=%SCRIPT_DIR%patch-config.txt"

echo Using root directory: "%ROOT_DIR%"
echo Using config: "%CONFIG_FILE%"

echo Checking for pwsh...
set _my_shell=pwsh

REM Check if pwsh.exe exists
where /q !_my_shell!
if !errorlevel! neq 0 (
  echo pwsh not found.
  echo.
  echo PowerShell 7 ^(pwsh^) is faster and recommended.
  set /p "INSTALL_PWSH=Would you like to install it now via winget? (Y/N): "
  if /I "!INSTALL_PWSH!"=="Y" (
    echo Installing PowerShell 7 via winget...
    winget install --id Microsoft.PowerShell --source winget --accept-package-agreements --accept-source-agreements
    if !errorlevel! neq 0 (
      echo Install failed or winget not available. Falling back to powershell...
      set _my_shell=powershell
    ) else (
      echo PowerShell 7 installed successfully.
      echo Please re-run GameUpdate.bat to use pwsh.
      pause
      exit /b 0
    )
  ) else (
    echo Skipping install. Falling back to powershell...
    set _my_shell=powershell
  )

  REM Check if powershell.exe exists
  echo Checking for powershell...
  where /q !_my_shell!
  if !errorlevel! neq 0 (
    echo.Error: Powershell not found!
    pause
    exit /B 1
  ) else (
    echo powershell found.
  )
) else (
  echo pwsh found.
)

echo Using !_my_shell! for script execution.

REM Check if patch-config.txt exists in gameupdate folder
if not exist "%CONFIG_FILE%" (
    echo "Config file (gameupdate\patch-config.txt) not found! Assuming no patching needed."
    pause
    exit /b
)

REM Read configuration from file
for /f "usebackq tokens=1,2 delims==" %%a in ("%CONFIG_FILE%") do (
    if "%%a"=="username" set "username=%%b"
    if "%%a"=="repo" set "repo=%%b"
    if "%%a"=="branch" set "branch=%%b"
)

REM --------------------------------------------------------
REM PRE-SETUP: Ensure SRPG data and patch structure exists
REM Run Steps 1 and 2 BEFORE pulling repo patch to avoid overwriting updates
REM 1) Unpack once if data folder doesn't exist (and data.dts does)
REM 2) Create Patch once if patch folder doesn't exist
REM --------------------------------------------------------
set "UNPACKER=%ROOT_DIR%\SRPG_Unpacker.exe"
if exist "%ROOT_DIR%\data.dts" (
    if exist "%UNPACKER%" (
        echo [Pre-Setup] Running SRPG_Unpacker preparation steps...

    REM Step 1: Unpack (once)
    if not exist "%ROOT_DIR%\data\" (
        set "SHOULD_UNPACK=1"
    ) else if not exist "%ROOT_DIR%\data\project.dat" (
        set "SHOULD_UNPACK=1"
    ) else (
        set "SHOULD_UNPACK=0"
    )
    
    if "!SHOULD_UNPACK!"=="1" (
            if exist "%ROOT_DIR%\data.dts" (
                echo [Pre-Setup] Step 1: Unpacking data.dts to data
                pushd "%ROOT_DIR%"
                "%UNPACKER%" -o "data" "data.dts"
                if !errorlevel! neq 0 (
                    echo [Pre-Setup] ERROR: Unpack failed. Continuing.
                )
                popd
            ) else (
                echo [Pre-Setup] Step 1: Skipping unpack - no data folder and no data.dts found.
            )
        ) else (
            echo [Pre-Setup] Step 1: data folder exists; skipping unpack.
        )

        REM Step 2: Create Patch (once)
        if not exist "%ROOT_DIR%\patch\" (
            if exist "%ROOT_DIR%\data\project.dat" (
                echo [Pre-Setup] Step 2: Creating patch from data\project.dat
                pushd "%ROOT_DIR%"
                "%UNPACKER%" ".\data\project.dat" -c
                if !errorlevel! neq 0 (
                    echo [Pre-Setup] ERROR: Create Patch failed. Continuing.
                )
                popd
            ) else (
                echo [Pre-Setup] Step 2: Skipping create patch - data\project.dat not found.
            )
        ) else (
            echo [Pre-Setup] Step 2: patch folder exists; skipping create.
        )
    ) else (
        echo [Pre-Setup] SRPG_Unpacker.exe not found in root; skipping pre-setup steps.
    )
) else (
    echo [Pre-Setup] data.dts not found; skipping pre-setup SRPG steps.
)

REM Get the latest hash
echo "Getting latest commit SHA hash"
!_my_shell! -Command "(Invoke-RestMethod -Uri 'https://gitgud.io/api/v4/projects/%username%%%2F%repo%/repository/branches/%branch%').commit.id" > "%ROOT_DIR%\latest_patch_sha.txt"

REM Read the latest SHA from the file
set /p latest_patch_sha=<"%ROOT_DIR%\latest_patch_sha.txt"

REM Check if previous_patch_sha.txt exists in gameupdate
if not exist "%SCRIPT_DIR%previous_patch_sha.txt" (
    echo "Previous SHA hash not found!"
    echo "Assuming first time patching..."
    goto download_extract
)

REM Read the stored SHA from previous check
set /p previous_patch_sha=<"%SCRIPT_DIR%previous_patch_sha.txt"

REM Trim whitespace from SHA strings
set "previous_patch_sha=%previous_patch_sha: =%"
set "latest_patch_sha=%latest_patch_sha: =%"

REM Compare trimmed SHAs
if "%latest_patch_sha%" neq "%previous_patch_sha%" (
    echo "Update found! Patching..."
    goto download_extract
) else (
    echo "Patch is up to date."
)

REM Delete latest_patch_sha.txt
del "%ROOT_DIR%\latest_patch_sha.txt"

endlocal
pause
exit /b

:download_extract

REM Escape single quotes in paths
set "escaped_root=%ROOT_DIR:'=''%" 

REM Download zip file to root
echo "Downloading latest patch..."
!_my_shell! -Command "Set-Location -LiteralPath '%escaped_root%'; $ProgressPreference = 'SilentlyContinue'; Invoke-WebRequest -Uri 'https://gitgud.io/%username%/%repo%/-/archive/%branch%/%repo%-%branch%.zip' -OutFile 'repo.zip'"
if !errorlevel! neq 0 (
    pause
    exit /b
)

REM Extract contents, overwriting conflicts into root
echo "Extracting..."
!_my_shell! -Command "Set-Location -LiteralPath '%escaped_root%'; $ProgressPreference = 'SilentlyContinue'; Expand-Archive -Path '.\repo.zip' -DestinationPath '.' -Force"
if !errorlevel! neq 0 (
    echo Extraction failed!
    del "%ROOT_DIR%\repo.zip"
    rmdir /s /q "%ROOT_DIR%\%repo%-%branch%"
    pause
    exit /b
)
echo "Applying patch..."
xcopy /s /e /y "%ROOT_DIR%\%repo%-%branch%\*" "%ROOT_DIR%\"
if !errorlevel! neq 0 (
    echo Patch application failed!
    del "%ROOT_DIR%\repo.zip"
    rmdir /s /q "%ROOT_DIR%\%repo%-%branch%"
    pause
    exit /b
)
REM --------------------------------------------------------
REM POST-APPLY: Run Steps 3 and 4 after patch files are merged
REM 3) Apply Patch to data\project.dat
REM 4) Pack data back into data.dts
REM --------------------------------------------------------
set "UNPACKER=%ROOT_DIR%\SRPG_Unpacker.exe"
if exist "%ROOT_DIR%\data.dts" (
    if exist "%UNPACKER%" (
        echo Running SRPG_Unpacker apply/pack steps...

        REM Step 3: Apply Patch
        if exist "%ROOT_DIR%\data\project.dat" (
            echo Step 3: Applying patch to data\project.dat
            pushd "%ROOT_DIR%"
            "%UNPACKER%" ".\data\project.dat" -a
            if !errorlevel! neq 0 (
                echo ERROR: Apply Patch failed.
            )
            popd
        ) else (
            echo ERROR: data\project.dat not found; cannot apply patch.
        )

        REM Step 4: Pack
        if exist "%ROOT_DIR%\data\" (
            echo Step 4: Packing data to data.dts
            pushd "%ROOT_DIR%"
            "%UNPACKER%" -o "data.dts" "data"
            if !errorlevel! neq 0 (
                echo WARNING: Pack failed.
            )
            popd
        ) else (
            echo Step 4: Skipping pack - data folder not found.
        )
    ) else (
        echo SRPG_Unpacker.exe not found in root; skipping SRPG patch steps.
    )
) else (
    echo data.dts not found; skipping SRPG patch steps.
)
REM Clean up
echo "Cleaning up..."
del "%ROOT_DIR%\repo.zip"
rmdir /s /q "%ROOT_DIR%\%repo%-%branch%"
del "%ROOT_DIR%\latest_patch_sha.txt"
REM Store latest SHA for next check in gameupdate
echo %latest_patch_sha% > "%SCRIPT_DIR%previous_patch_sha.txt"
endlocal
pause
exit /b
