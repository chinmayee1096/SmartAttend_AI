@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python Launcher was not found. Install Python 3.12 and try again.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the Python virtual environment...
    py -3.12 -m venv .venv
    if errorlevel 1 exit /b 1
)

echo Installing SmartAttend AI dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo.
echo Setup completed. Run run_app.bat to start SmartAttend AI.
endlocal

