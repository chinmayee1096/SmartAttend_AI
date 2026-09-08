@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo SmartAttend AI is not set up yet.
    echo Run setup.bat first, then run this file again.
    pause
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -m streamlit run "%~dp0streamlit_app.py" --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
pause
endlocal
