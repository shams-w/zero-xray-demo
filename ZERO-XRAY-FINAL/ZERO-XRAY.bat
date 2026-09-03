@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title ZERO X-RAY

rem =====================================================================
rem  ZERO-XRAY.bat
rem  Single entry point for a normal user: double-click this file.
rem  - First time (setup never completed): runs setup.bat, then launches.
rem  - Every time after: launches immediately via run_project.bat.
rem
rem  "Setup completed" is detected by the presence of BOTH the backend
rem  virtual environment and the frontend dependencies -- the same two
rem  things setup.bat creates and run_project.bat itself depends on.
rem  Does NOT modify any project code, UI, database logic, auth,
rem  multi-tenancy, or Future Engine behavior.
rem =====================================================================

set "PROJECT_ROOT=%~dp0"
set "SERVER_DIR=%PROJECT_ROOT%server"
set "CLIENT_DIR=%PROJECT_ROOT%client"

echo =====================================================
echo   ZERO X-RAY
echo =====================================================
echo.

set "SETUP_DONE=1"
if not exist "%SERVER_DIR%\.venv\Scripts\python.exe" set "SETUP_DONE=0"
if not exist "%CLIENT_DIR%\node_modules" set "SETUP_DONE=0"

if "!SETUP_DONE!"=="0" (
    echo First run detected -- running one-time setup first ...
    echo.
    call "%PROJECT_ROOT%setup.bat"
    if not !errorlevel! equ 0 (
        echo.
        echo ERROR: Setup did not complete successfully -- see the messages above.
        echo.
        pause
        exit /b 1
    )
    echo.
    echo Setup complete -- launching ZERO X-RAY ...
    echo.
) else (
    echo Existing setup detected -- launching ZERO X-RAY ...
    echo.
)

call "%PROJECT_ROOT%run_project.bat"
endlocal
