@echo off
setlocal EnableExtensions

echo ================================================
echo Reservation Manager - Windows UI Runner
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

echo [STEP] Preparing virtual environment...
if not exist ".venv\Scripts\python.exe" (
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        exit /b 1
    )
)

echo [STEP] Installing dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
.venv\Scripts\python.exe -m pip install PyYAML Flask >nul
if errorlevel 1 (
    echo [ERROR] Failed to install Python dependencies.
    exit /b 1
)

echo [STEP] Launching UI server on http://127.0.0.1:5000
start "" http://127.0.0.1:5000
.venv\Scripts\python.exe -c "from reservation_manager.web_app import create_app; app=create_app(); app.run(host='127.0.0.1', port=5000, debug=False)"

endlocal
exit /b 0
