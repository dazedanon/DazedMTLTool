@echo off
setlocal EnableExtensions

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

echo Root: %ROOT_DIR%

setlocal EnableDelayedExpansion

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
    pause
    exit /b 1
  )
)

REM Check if patch-config.txt exists in gameupdate folder
if not exist "%CONFIG_FILE%" (
    echo Config file gameupdate\patch-config.txt not found - skipping patch.
    pause
    exit /b
)

REM Read configuration from file
for /f "usebackq tokens=1,2 delims==" %%a in ("%CONFIG_FILE%") do (
    if "%%a"=="username" set "username=%%b"
    if "%%a"=="repo" set "repo=%%b"
    if "%%a"=="branch" set "branch=%%b"
)

REM Validate required config keys early for clearer errors
if "%username%"=="" (
    echo ERROR: 'username=' is missing in gameupdate\patch-config.txt
    pause
    exit /b 1
)
if "%repo%"=="" (
    echo ERROR: 'repo=' is missing in gameupdate\patch-config.txt
    pause
    exit /b 1
)
if "%branch%"=="" (
    echo ERROR: 'branch=' is missing in gameupdate\patch-config.txt
    pause
    exit /b 1
)

REM For PowerShell (proper URL encoding; avoids cmd %% pitfalls)
set "GU_USERNAME=%username%"
set "GU_REPO=%repo%"
set "GU_BRANCH=%branch%"

REM --------------------------------------------------------
REM PRE-SETUP: Ensure SRPG data and patch structure exists
REM Run Steps 1 and 2 BEFORE pulling repo patch to avoid overwriting updates
REM 1) Unpack once if data folder doesn't exist (and data.dts does)
REM 2) Create Patch once if patch folder doesn't exist
REM --------------------------------------------------------
set "UNPACKER=%ROOT_DIR%\SRPG_Unpacker.exe"
if exist "%ROOT_DIR%\data.dts" (
    if exist "%UNPACKER%" (
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
                echo [Pre-Setup] Unpacking data.dts to data\
                pushd "%ROOT_DIR%"
                "%UNPACKER%" -o "data" "data.dts"
                if !errorlevel! neq 0 (
                    echo [Pre-Setup] ERROR: Unpack failed. Continuing.
                )
                popd
            ) else (
                echo [Pre-Setup] Skipping unpack: data.dts missing.
            )

        REM Step 2: Create Patch (once)
        if not exist "%ROOT_DIR%\patch\" (
            if exist "%ROOT_DIR%\data\project.dat" (
                echo [Pre-Setup] Creating patch folder from data\project.dat
                pushd "%ROOT_DIR%"
                "%UNPACKER%" ".\data\project.dat" -c
                if !errorlevel! neq 0 (
                    echo [Pre-Setup] ERROR: Create Patch failed. Continuing.
                )
                popd
            ) else (
                echo [Pre-Setup] Skipping create patch: data\project.dat not found.
            )
        )
    ) else (
        REM SHOULD_UNPACK=0: only Step 2 may still be needed
        if not exist "%ROOT_DIR%\patch\" (
            if exist "%ROOT_DIR%\data\project.dat" (
                echo [Pre-Setup] Creating patch folder from data\project.dat
                pushd "%ROOT_DIR%"
                "%UNPACKER%" ".\data\project.dat" -c
                if !errorlevel! neq 0 (
                    echo [Pre-Setup] ERROR: Create Patch failed. Continuing.
                )
                popd
            ) else (
                echo [Pre-Setup] Skipping create patch: data\project.dat not found.
            )
        )
    )
    ) else (
        echo [Pre-Setup] SRPG_Unpacker.exe not found; skipping data setup.
    )
)

:download_extract

REM Download/extract via patch-download.ps1 (IWR-based); Bypass avoids ExecutionPolicy prompts
if not exist "%SCRIPT_DIR%patch-download.ps1" (
    echo ERROR: patch-download.ps1 not found next to patch.bat in the gameupdate folder.
    pause
    exit /b 1
)
!_my_shell! -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%patch-download.ps1" -GameRoot "%ROOT_DIR%" -StateFile "%SCRIPT_DIR%previous_patch_sha.txt"
set "PATCH_DL_EXIT=!errorlevel!"
if "!PATCH_DL_EXIT!"=="10" (
    echo Already up to date.
    endlocal
    pause
    exit /b 0
)
if not "!PATCH_DL_EXIT!"=="0" (
    echo Download or extraction failed^!
    if exist "%ROOT_DIR%\repo.zip" del "%ROOT_DIR%\repo.zip"
    if exist "%ROOT_DIR%\_patch_extract_tmp" rmdir /s /q "%ROOT_DIR%\_patch_extract_tmp"
    pause
    exit /b 1
)
echo Applying patch...
REM Files merged by Copy-Item above
REM --------------------------------------------------------
REM POST-APPLY: Run Steps 3 and 4 after patch files are merged
REM 3) Apply Patch to data\project.dat
REM 4) Pack data back into data.dts
REM --------------------------------------------------------
set "UNPACKER=%ROOT_DIR%\SRPG_Unpacker.exe"
if exist "%ROOT_DIR%\data.dts" (
    if exist "%UNPACKER%" (
        REM Step 3: Apply Patch
        if exist "%ROOT_DIR%\data\project.dat" (
            echo Applying patch to data\project.dat...
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
            echo Packing data folder to data.dts...
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
)
REM Clean up
echo Cleaning up...
del "%ROOT_DIR%\repo.zip"
if exist "%ROOT_DIR%\_patch_extract_tmp" rmdir /s /q "%ROOT_DIR%\_patch_extract_tmp"
endlocal
pause
exit /b
