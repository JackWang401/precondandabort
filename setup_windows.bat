@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python was not found.
    echo Install 64-bit Python 3.12 from https://www.python.org/downloads/windows/
    echo During installation, enable the Python launcher and Tcl/Tk support.
    pause
    exit /b 1
)

py -3.12 -c "import sys"
if errorlevel 1 (
    echo The Windows deployment scripts require 64-bit Python 3.12.
    echo Install Python 3.12 from https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the Windows virtual environment...
    py -3.12 -m venv .venv
    if errorlevel 1 goto :failed
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 goto :failed
python -m pip install -r requirements.txt
if errorlevel 1 goto :failed
python -c "import tkinter; import asammdf; import numpy; import openpyxl; import numbers_parser"
if errorlevel 1 goto :failed

echo.
echo Setup completed successfully.
echo Double-click run_windows.bat to start the application.
pause
exit /b 0

:failed
echo.
echo Setup failed. Review the error messages above.
pause
exit /b 1
