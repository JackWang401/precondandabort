@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo The application environment is not installed.
    echo Run setup_windows.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "run_app.py"
if errorlevel 1 (
    echo.
    echo The application closed because of an error.
    pause
    exit /b 1
)
