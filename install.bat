@echo off
REM ==================================================================
REM  Perfusion System Hydraulic Simulator V1.0 - installation (Windows)
REM  Creates a local virtual environment in .venv and installs packages.
REM ==================================================================
setlocal
cd /d "%~dp0"
echo.
echo === Perfusion System Hydraulic Simulator V1.0 - Installation ===
echo.

set "PY="
where py >nul 2>nul && (py -3.12 -c "import sys" >nul 2>nul && set "PY=py -3.12")
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [ERROR] Python was not found.
    echo         Please install Python 3.12 from https://www.python.org/downloads/
    echo         and tick "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)

%PY% -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3,11) else 1)"
if errorlevel 1 (
    echo [ERROR] Python 3.11 or newer is required ^(3.12 recommended^). Found:
    %PY% --version
    pause
    exit /b 1
)
echo Using:
%PY% --version

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
)

echo Upgrading pip ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
echo Installing required packages (this can take a few minutes) ...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Package installation failed. Check your internet connection / proxy and run install.bat again.
    pause
    exit /b 1
)

echo.
echo Optional: Chrome for static figure export (PNG/SVG/PDF via Kaleido).
echo If Google Chrome is not installed, Kaleido can download a private copy now.
".venv\Scripts\python.exe" -c "import plotly.io as pio; import kaleido; print('kaleido', kaleido.__version__)"
".venv\Scripts\plotly_get_chrome.exe" -y >nul 2>nul
echo (If this step failed, figure export falls back to Matplotlib automatically.)

echo.
echo Running the automated test-suite ...
".venv\Scripts\python.exe" -m pytest -q --ignore=tests/test_ui_smoke.py
if errorlevel 1 (
    echo [WARNING] Some tests failed - see output above. The application may still start.
) else (
    echo All tests passed.
)
echo.
echo Installation finished. Start the application with a double-click on start.bat
pause
