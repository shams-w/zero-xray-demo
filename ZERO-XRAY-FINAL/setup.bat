@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title ZERO X-RAY - Setup

rem =====================================================================
rem  setup.bat
rem  One-time setup for ZERO X-RAY. Safe to re-run any time -- every
rem  step below is idempotent (skips work that's already done, or lets
rem  pip/npm do their own normal incremental update).
rem  Does NOT modify any project code, UI, database logic, auth,
rem  multi-tenancy, or Future Engine behavior. Packaging/setup only.
rem =====================================================================

set "PROJECT_ROOT=%~dp0"
set "SERVER_DIR=%PROJECT_ROOT%server"
set "CLIENT_DIR=%PROJECT_ROOT%client"

echo =====================================================
echo   ZERO X-RAY -- One-Time Setup
echo   Project root: "%PROJECT_ROOT%"
echo =====================================================
echo.

if not exist "%SERVER_DIR%\main.py" (
    echo ERROR: Backend not found at "%SERVER_DIR%".
    echo   Make sure setup.bat sits next to the "server" and "client" folders.
    pause
    exit /b 1
)
if not exist "%CLIENT_DIR%\package.json" (
    echo ERROR: Frontend not found at "%CLIENT_DIR%".
    echo   Make sure setup.bat sits next to the "server" and "client" folders.
    pause
    exit /b 1
)

rem =====================================================================
rem  1. Python
rem =====================================================================
echo [1/9] Checking Python ...
set "PY_LAUNCHER="
where py >nul 2>nul
if !errorlevel! equ 0 (
    set "PY_LAUNCHER=py -3"
) else (
    where python >nul 2>nul
    if !errorlevel! equ 0 (
        set "PY_LAUNCHER=python"
    )
)
if "!PY_LAUNCHER!"=="" (
    echo.
    echo ERROR: Python was not found on PATH.
    echo   Install Python 3.12+ from: https://www.python.org/downloads/windows/
    echo   During install, check "Add python.exe to PATH". Then re-run setup.bat.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%V in ('!PY_LAUNCHER! --version 2^>^&1') do echo   Found: %%V

rem =====================================================================
rem  2/3. Create + activate the virtual environment (skip creation if
rem  it already exists -- do not reinstall everything unnecessarily)
rem =====================================================================
echo.
echo [2/9] Checking backend virtual environment ...
if exist "%SERVER_DIR%\.venv\Scripts\python.exe" (
    echo   "server\.venv" already exists -- skipping creation.
) else (
    echo   Creating "server\.venv" ...
    !PY_LAUNCHER! -m venv "%SERVER_DIR%\.venv"
    if not exist "%SERVER_DIR%\.venv\Scripts\python.exe" (
        echo.
        echo ERROR: Failed to create the Python virtual environment.
        pause
        exit /b 1
    )
)

echo.
echo [3/9] Activating virtual environment ...
call "%SERVER_DIR%\.venv\Scripts\activate.bat"
if not !errorlevel! equ 0 (
    echo ERROR: Failed to activate "server\.venv".
    pause
    exit /b 1
)

rem =====================================================================
rem  4. Backend dependencies
rem =====================================================================
echo.
echo [4/9] Installing/updating backend requirements ...
python -m pip install --upgrade pip
if not !errorlevel! equ 0 (
    echo ERROR: Failed to upgrade pip in the virtual environment.
    pause
    exit /b 1
)
python -m pip install -r "%SERVER_DIR%\requirements.txt"
if not !errorlevel! equ 0 (
    echo.
    echo ERROR: Failed to install backend requirements.
    echo   Check your internet connection and re-run setup.bat.
    pause
    exit /b 1
)
echo   Backend requirements installed.

rem =====================================================================
rem  5. Node.js / npm
rem =====================================================================
echo.
echo [5/9] Checking Node.js / npm ...
where npm >nul 2>nul
if not !errorlevel! equ 0 (
    echo.
    echo ERROR: Node.js / npm was not found on PATH.
    echo   Install Node.js 18+ (LTS) from: https://nodejs.org/
    echo   Then re-run setup.bat.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%V in ('node --version 2^>^&1') do echo   Found Node.js: %%V
for /f "tokens=*" %%V in ('npm --version 2^>^&1') do echo   Found npm: %%V

rem =====================================================================
rem  6. Frontend dependencies -- uses the existing package.json /
rem  package-lock.json as-is, does not touch the lock file.
rem =====================================================================
echo.
echo [6/9] Installing frontend dependencies ...
pushd "%CLIENT_DIR%"
call npm install
set "NPM_INSTALL_RESULT=!errorlevel!"
popd
if not !NPM_INSTALL_RESULT! equ 0 (
    echo.
    echo ERROR: npm install failed in "%CLIENT_DIR%".
    pause
    exit /b 1
)
echo   Frontend dependencies installed.

rem =====================================================================
rem  7. Project environment configuration (.env)
rem =====================================================================
echo.
echo [7/9] Checking project environment configuration ...
if exist "%PROJECT_ROOT%.env" (
    echo   "%PROJECT_ROOT%.env" already exists -- leaving it as-is.
) else (
    if exist "%PROJECT_ROOT%.env.example" (
        copy /y "%PROJECT_ROOT%.env.example" "%PROJECT_ROOT%.env" >nul
        python -c "from pathlib import Path; import secrets; p=Path(r'%PROJECT_ROOT%.env'); s=p.read_text(encoding='utf-8'); s=s.replace('ZX_DEMO_DEV_PASSPHRASE=<set-a-local-demo-passphrase>', 'ZX_DEMO_DEV_PASSPHRASE='+secrets.token_urlsafe(18)); p.write_text(s, encoding='utf-8')"
        echo   Created "%PROJECT_ROOT%.env" from .env.example and generated a local demo passphrase.
    ) else (
        echo   WARNING: .env.example not found -- skipping .env creation.
    )
)

rem =====================================================================
rem  8/9. Ollama + configured model
rem =====================================================================
echo.
echo [8/9] Checking Ollama ...
call "%PROJECT_ROOT%check_ollama.bat"
set "OLLAMA_CHECK_RESULT=!errorlevel!"
if not !OLLAMA_CHECK_RESULT! equ 0 (
    echo.
    echo Setup could not finish because Ollama is not ready ^(see message above^).
    echo   You can fix this and re-run setup.bat, or run check_ollama.bat by itself
    echo   once Ollama is installed to finish preparing the model.
    pause
    exit /b !OLLAMA_CHECK_RESULT!
)
echo [9/9] Ollama and the configured model are ready.

echo.
echo =====================================================
echo   SETUP COMPLETE
echo =====================================================
echo.
echo   Backend venv   : server\.venv
echo   Frontend deps  : client\node_modules
echo   Config file    : .env
echo   Ollama model   : ready
echo.
echo   Next step: double-click run_project.bat ^(or ZERO-XRAY.bat^) to start ZERO X-RAY.
echo.
pause
endlocal
