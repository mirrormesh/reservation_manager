@echo off
setlocal EnableExtensions

echo ================================================
echo Reservation Manager - First Run Setup
echo ================================================
echo.

cd /d "%~dp0"
set "PYTHONPATH=%CD%"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY_CMD=py -3"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PY_CMD=python"
    ) else (
        echo [ERROR] Python 3 is not installed.
        echo [INFO] Install Python 3.9+ from https://www.python.org/downloads/windows/
        exit /b 1
    )
)

echo [STEP] Creating virtual environment (.venv)...
if not exist ".venv\Scripts\python.exe" (
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        exit /b 1
    )
) else (
    echo [OK] Existing virtual environment found.
)

echo [STEP] Installing Python dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
if errorlevel 1 (
    echo [ERROR] Failed to upgrade pip.
    exit /b 1
)
.venv\Scripts\python.exe -m pip install PyYAML Flask holidays >nul
if errorlevel 1 (
    echo [ERROR] Failed to install Python dependencies.
    exit /b 1
)

echo [STEP] Running Python tests...
.venv\Scripts\python.exe -m unittest discover -s tests -v
if errorlevel 1 (
    echo [ERROR] Python tests failed.
    exit /b 1
)

echo [STEP] Running Node tests (optional)...
where node >nul 2>nul
if %errorlevel%==0 (
    node --test nodejs/test/*.test.js
    if errorlevel 1 (
        echo [ERROR] Node tests failed.
        exit /b 1
    )
) else (
    echo [WARN] Node.js not found. Skipping Node tests.
)

echo [STEP] Generating initial sample data...
.venv\Scripts\python.exe -c "from datetime import datetime; from reservation_manager import ReservationYamlRepository; ReservationYamlRepository('data').seed_large_test_data(now=datetime.now(), days=30, slots_per_day=4, overwrite=True); print('sample_data_ready=True')"
if errorlevel 1 (
    echo [ERROR] Failed to generate sample data.
    exit /b 1
)

echo [STEP] Launching UI server on http://127.0.0.1:5000
start "" http://127.0.0.1:5000
.venv\Scripts\python.exe -m reservation_manager.web_app

endlocal
exit /b 0
