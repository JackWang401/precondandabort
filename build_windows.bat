@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Run setup_windows.bat before building the standalone application.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
python -m pip install -r requirements-build.txt
if errorlevel 1 goto :failed

python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --onefile ^
    --name "PrecondAbortAnalyzer" ^
    --collect-all "asammdf" ^
    --collect-all "numbers_parser" ^
    --add-data "PrecondAndAbort.xlsx;." ^
    "run_app.py"
if errorlevel 1 goto :failed

echo.
echo Build completed successfully.
echo Deploy dist\PrecondAbortAnalyzer.exe to Windows 11.
pause
exit /b 0

:failed
echo.
echo The Windows build failed. Review the error messages above.
pause
exit /b 1
