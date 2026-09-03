@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title ZERO X-RAY - Project Launcher

rem =====================================================================
rem  run_project.bat
rem  One-click launcher for ZERO X-RAY.
rem  - Checks/starts Ollama and verifies the configured model, and
rem    waits until both are ready before starting anything else.
rem  - Detects the project folder automatically (works with spaces and
rem    parentheses in the path).
rem  - Installs frontend dependencies automatically on first run if
rem    client\node_modules is missing.
rem  - Starts the FastAPI backend (server\) on 127.0.0.1:8000 and the
rem    Vite frontend (client\) on http://localhost:5173, each in its
rem    own window so their logs stay visible.
rem  - Waits for both to actually respond, then opens the frontend in
rem    the default browser automatically.
rem  - Does NOT modify any project code, UI, database logic, auth,
rem    multi-tenancy, or Future Engine behavior.
rem =====================================================================

set "PROJECT_ROOT=%~dp0"
set "SERVER_DIR=%PROJECT_ROOT%server"
set "CLIENT_DIR=%PROJECT_ROOT%client"
set "BACKEND_URL=http://127.0.0.1:8000"
set "FRONTEND_URL=http://localhost:5173"

echo =====================================================
echo   ZERO X-RAY -- Project Launcher
echo   Project root: "%PROJECT_ROOT%"
echo =====================================================
echo.

if not exist "%SERVER_DIR%\main.py" (
    echo ERROR: Backend not found at "%SERVER_DIR%".
    echo   Make sure run_project.bat sits next to the "server" and "client" folders.
    echo.
    pause
    exit /b 1
)

if not exist "%CLIENT_DIR%\package.json" (
    echo ERROR: Frontend not found at "%CLIENT_DIR%".
    echo   Make sure run_project.bat sits next to the "server" and "client" folders.
    echo.
    pause
    exit /b 1
)

rem =====================================================================
rem  Step 1: Ollama must be ready BEFORE we start anything else --
rem  ZERO X-RAY's Analyze pipeline requires it by default (Mandatory
rem  AI Mode / REQUIRE_OLLAMA). Reuses the exact same check setup.bat
rem  uses (see check_ollama.bat).
rem =====================================================================
echo [1/5] Checking Ollama and the configured model ...
call "%PROJECT_ROOT%check_ollama.bat"
if not !errorlevel! equ 0 (
    echo.
    echo ERROR: Ollama is not ready -- see the message above.
    echo   ZERO X-RAY will not start until Ollama and the configured model
    echo   are available. Run setup.bat, or fix the issue above and try again.
    echo.
    pause
    exit /b 1
)
echo [1/5] Ollama and the model are ready.

rem =====================================================================
rem  Step 2: pick a Python interpreter -- prefer the project venv.
rem =====================================================================
echo.
echo [2/5] Preparing backend interpreter ...
set "VENV_PY=%SERVER_DIR%\.venv\Scripts\python.exe"
set "PYTHON_EXE="
set "PYTHON_ARGS="

if exist "%VENV_PY%" (
    set "PYTHON_EXE=%VENV_PY%"
    echo   Using project virtual environment: "%VENV_PY%"
) else (
    where py >nul 2>nul
    if !errorlevel! equ 0 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3"
        echo   No server\.venv found -- using system launcher: py -3
        echo   TIP: run setup.bat once to create server\.venv with the exact
        echo        pinned backend dependencies.
    ) else (
        where python >nul 2>nul
        if !errorlevel! equ 0 (
            set "PYTHON_EXE=python"
            echo   No server\.venv found -- using system Python: python
        ) else (
            echo.
            echo ERROR: No Python interpreter found.
            echo   Install Python 3.12+, or run setup.bat first, then try again.
            echo.
            pause
            exit /b 1
        )
    )
)

where npm >nul 2>nul
if not !errorlevel! equ 0 (
    echo.
    echo ERROR: npm was not found on PATH. Install Node.js 18+, then try again.
    echo.
    pause
    exit /b 1
)

rem =====================================================================
rem  Step 3: frontend dependencies -- install automatically on first
rem  run only, before starting Vite.
rem =====================================================================
echo.
echo [3/5] Checking frontend dependencies ...
if not exist "%CLIENT_DIR%\node_modules" (
    echo   client\node_modules not found -- installing ^(npm install^) ...
    pushd "%CLIENT_DIR%"
    call npm install
    if not !errorlevel! equ 0 (
        popd
        echo.
        echo ERROR: npm install failed in "%CLIENT_DIR%".
        echo   Fix the error shown above, then run this file again.
        echo.
        pause
        exit /b 1
    )
    popd
    echo   Frontend dependencies installed successfully.
) else (
    echo   client\node_modules already present -- skipping npm install.
)

rem =====================================================================
rem  Step 4: start backend + frontend, each in its own window so logs
rem  stay visible, then wait for both to actually respond.
rem  NOTE: ZX_DATA_ROOT is intentionally left unset here -- the backend
rem  picks its own safe default (D:\ZERO-XRAY-DATA if a D: drive
rem  exists, otherwise a ZERO-XRAY-DATA folder under the user's home
rem  directory -- see server/core/data_paths.py). Forcing D:\ from
rem  this launcher would break on any machine without a D: drive.
rem =====================================================================
echo.
echo [4/5] Starting Backend  ^(FastAPI - %BACKEND_URL%^) ...
start "ZERO X-RAY Backend - FastAPI (%BACKEND_URL%)" cmd /k "cd /d "%SERVER_DIR%" && "!PYTHON_EXE!" !PYTHON_ARGS! -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload"

echo         Starting Frontend ^(Vite - %FRONTEND_URL%^) ...
start "ZERO X-RAY Frontend - Vite (%FRONTEND_URL%)" cmd /k "cd /d "%CLIENT_DIR%" && npm run dev"

echo.
echo [5/5] Waiting for Backend and Frontend to become ready ...

set "BACKEND_READY=0"
set "WAIT_TRIES=0"
:wait_for_backend
set /a WAIT_TRIES+=1
curl -s -m 3 -o nul -w "" "%BACKEND_URL%/api/health" >nul 2>nul
if !errorlevel! equ 0 (
    set "BACKEND_READY=1"
    goto :backend_ready
)
if !WAIT_TRIES! lss 30 (
    timeout /t 2 /nobreak >nul
    goto :wait_for_backend
)
:backend_ready
if "!BACKEND_READY!"=="1" (
    echo         Backend is responding at %BACKEND_URL%.
) else (
    echo.
    echo ERROR: Backend failed to start ^(no response from %BACKEND_URL%/api/health
    echo   after 60 seconds^). Check the Backend window for the actual error.
    echo.
    pause
    exit /b 1
)

set "FRONTEND_READY=0"
set "WAIT_TRIES=0"
:wait_for_frontend
set /a WAIT_TRIES+=1
curl -s -m 3 -o nul -w "" "%FRONTEND_URL%" >nul 2>nul
if !errorlevel! equ 0 (
    set "FRONTEND_READY=1"
    goto :frontend_ready
)
if !WAIT_TRIES! lss 30 (
    timeout /t 2 /nobreak >nul
    goto :wait_for_frontend
)
:frontend_ready
if "!FRONTEND_READY!"=="1" (
    echo         Frontend is responding at %FRONTEND_URL%.
) else (
    echo.
    echo ERROR: Frontend failed to start ^(no response from %FRONTEND_URL%
    echo   after 60 seconds^). Check the Frontend window for the actual error.
    echo.
    pause
    exit /b 1
)

echo.
echo Opening ZERO X-RAY in your default browser ...
start "" "%FRONTEND_URL%"

echo.
echo =====================================================
echo   ZERO X-RAY is running.
echo   Backend  :  %BACKEND_URL%
echo   Frontend :  %FRONTEND_URL%
echo.
echo   Keep the Backend and Frontend windows open while you
echo   use the app -- closing them stops the project.
echo =====================================================
echo.
echo You can close THIS window now; the Backend and Frontend
echo windows will keep running on their own.
echo.
pause
endlocal
