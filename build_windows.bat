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
    --onedir ^
    --name "PrecondAbortAnalyzer" ^
    --collect-all "asammdf" ^
    --collect-all "numbers_parser" ^
    --add-data "PrecondAndAbort.xlsx;." ^
    "run_app.py"
if errorlevel 1 goto :failed

copy /Y "README.md" "dist\PrecondAbortAnalyzer\README.md" >nul
echo.
echo Build completed successfully.
echo Deploy the entire dist\PrecondAbortAnalyzer folder to Windows 11.
echo Start it with PrecondAbortAnalyzer.exe.
pause
exit /b 0

:failed
echo.
echo The Windows build failed. Review the error messages above.
pause
exit /b 1
