@echo off
REM Start the Perfusion System Hydraulic Simulator V1.0 in the local browser.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] The application is not installed yet. Please run install.bat first.
    pause
    exit /b 1
)
echo Starting Perfusion System Hydraulic Simulator V1.0 ...
echo The application opens in your browser at http://localhost:8501
echo Close this window to stop the application.
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless false --server.port 8501 --browser.gatherUsageStats false
if errorlevel 1 (
    echo [ERROR] The application terminated with an error. Port 8501 may be in use - close other instances and retry.
    pause
)
