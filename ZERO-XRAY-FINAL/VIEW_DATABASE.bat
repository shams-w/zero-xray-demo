@echo off
setlocal
set "PROJECT_ROOT=%~dp0"
set "SERVER_DIR=%PROJECT_ROOT%server"
set "VENV_PY=%SERVER_DIR%\.venv\Scripts\python.exe"

cd /d "%SERVER_DIR%"

if exist "%VENV_PY%" (
  "%VENV_PY%" -m tools.export_database_view
) else (
  py -3 -m tools.export_database_view
)

if errorlevel 1 (
  echo.
  echo Could not export database.
  pause
  exit /b 1
)

if exist "D:\ZERO-XRAY-DATA\database_view" (
  explorer "D:\ZERO-XRAY-DATA\database_view"
) else (
  explorer "%USERPROFILE%\ZERO-XRAY-DATA\database_view"
)

endlocal
