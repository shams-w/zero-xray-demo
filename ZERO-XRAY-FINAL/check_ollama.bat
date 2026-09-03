@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem =====================================================================
rem  check_ollama.bat
rem  Shared Ollama readiness check -- called by SETUP.bat and
rem  RUN_PROJECT.bat (via "call check_ollama.bat") so both use the exact
rem  same logic instead of two copies drifting apart.
rem
rem  What it does, in order:
rem    1. Checks Ollama is installed (on PATH).
rem    2. Checks the Ollama service is reachable on 127.0.0.1:11434;
rem       starts it ("ollama serve") if installed but not running, then
rem       waits for it to come up.
rem    3. Checks the configured model (OLLAMA_MODEL, read from .env if
rem       present, else the project default below) is already pulled;
rem       runs "ollama pull <model>" if not.
rem
rem  Does NOT modify any project code. Exits with:
rem    0  = Ollama + model ready
rem    1  = Ollama not installed
rem    2  = Ollama installed but could not be started / never became reachable
rem    3  = model missing and could not be pulled
rem =====================================================================

rem ---------------------------------------------------------------
rem Resolve the model name: prefer OLLAMA_MODEL from a real .env file
rem next to this script (so a user who customized it gets the right
rem model pulled), else fall back to the project's current default.
rem Never invents/guesses a different model.
rem ---------------------------------------------------------------
set "PROJECT_ROOT=%~dp0"
set "OLLAMA_MODEL=qwen3:4b"
if exist "%PROJECT_ROOT%.env" (
    for /f "usebackq tokens=1,* delims== eol=#" %%A in ("%PROJECT_ROOT%.env") do (
        if /i "%%A"=="OLLAMA_MODEL" if not "%%B"=="" set "OLLAMA_MODEL=%%B"
    )
)

echo.
echo [Ollama] Checking Ollama installation ...
where ollama >nul 2>nul
if not !errorlevel! equ 0 (
    echo.
    echo ERROR: Ollama is not installed.
    echo   ZERO X-RAY requires Ollama to run AI-dependent analysis.
    echo   Download and install it from: https://ollama.com/download/windows
    echo   After installing, close and re-run this script.
    echo.
    exit /b 1
)
echo [Ollama] Found: 
where ollama

rem ---------------------------------------------------------------
rem Is the Ollama API already reachable? Try curl (built into
rem Windows 10 1803+/Windows 11) against /api/version.
rem ---------------------------------------------------------------
echo [Ollama] Checking whether the Ollama service is running ...
curl -s -m 3 -o nul -w "" http://127.0.0.1:11434/api/version >nul 2>nul
if !errorlevel! equ 0 (
    echo [Ollama] Service is already running.
    goto :check_model
)

echo [Ollama] Not running yet -- starting it in the background ...
start "" /min ollama serve

set "OLLAMA_WAIT_TRIES=0"
:wait_for_ollama
set /a OLLAMA_WAIT_TRIES+=1
timeout /t 2 /nobreak >nul
curl -s -m 3 -o nul -w "" http://127.0.0.1:11434/api/version >nul 2>nul
if !errorlevel! equ 0 (
    echo [Ollama] Service is now running.
    goto :check_model
)
if !OLLAMA_WAIT_TRIES! lss 15 goto :wait_for_ollama

echo.
echo ERROR: Ollama did not become reachable at http://127.0.0.1:11434 after starting it.
echo   Try starting Ollama manually (open the Ollama app, or run "ollama serve"
echo   in a separate window) and re-run this script.
echo.
exit /b 2

:check_model
echo [Ollama] Checking whether model "%OLLAMA_MODEL%" is already pulled ...
ollama list 2>nul | findstr /i /c:"%OLLAMA_MODEL%" >nul 2>nul
if !errorlevel! equ 0 (
    echo [Ollama] Model "%OLLAMA_MODEL%" is already available.
    exit /b 0
)

echo [Ollama] Model "%OLLAMA_MODEL%" not found locally -- pulling it now.
echo   This can take a while the first time depending on your connection.
ollama pull %OLLAMA_MODEL%
if not !errorlevel! equ 0 (
    echo.
    echo ERROR: Required Ollama model is missing and could not be downloaded.
    echo   Try running "ollama pull %OLLAMA_MODEL%" manually and re-run this script.
    echo.
    exit /b 3
)

echo [Ollama] Model "%OLLAMA_MODEL%" is ready.
exit /b 0
