@echo off
setlocal EnableExtensions

set "MODE=%~1"
if not defined MODE set "MODE=first-run"

if /I "%MODE%"=="first-run" (
    set "RUN_SAMPLE_DATA=1"
    set "RUN_UI=1"
    set "RUN_QUICKCHECK=0"
    set "SCRIPT_TITLE=Reservation Manager - First Run Setup"
) else (
    if /I "%MODE%"=="check" (
        set "RUN_SAMPLE_DATA=0"
        set "RUN_UI=0"
        set "RUN_QUICKCHECK=1"
        set "SCRIPT_TITLE=Reservation Manager - Windows One-Click Check"
    ) else (
        echo [ERROR] Unknown mode "%MODE%".
        echo Usage:
        echo    %~nx0 [first-run^|check]
        exit /b 1
    )
)

echo ================================================
echo %SCRIPT_TITLE%
echo ================================================
echo.
echo [INFO] Running mode: %MODE%
echo.

cd /d "%~dp0"
set "PYTHONPATH=%CD%"

set "PY_CMD="
call :detect_python
if not defined PY_CMD (
    echo [WARN] Python 3 is not installed.
    echo [INFO] Attempting automatic install of Python 3.11...
    call :install_python
    if errorlevel 1 (
        echo [ERROR] Automatic Python installation failed.
        goto :FAIL
    )
    call :detect_python
    if not defined PY_CMD call :locate_installed_python
    if not defined PY_CMD (
        echo [ERROR] Python installation finished but interpreter not found.
        echo [INFO] Please restart this terminal or install Python 3.9+ from https://www.python.org/downloads/windows/
        goto :FAIL
    )
)

echo [OK] Python found: %PY_CMD%

echo [STEP] Creating virtual environment (.venv)...
if not exist ".venv\Scripts\python.exe" (
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        goto :FAIL
    )
) else (
    echo [OK] Existing virtual environment found.
)

echo [STEP] Installing Python dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
if errorlevel 1 (
    echo [ERROR] Failed to upgrade pip.
    goto :FAIL
)
.venv\Scripts\python.exe -m pip install PyYAML Flask holidays >nul
if errorlevel 1 (
    echo [ERROR] Failed to install Python dependencies.
    goto :FAIL
)

echo [STEP] Running Python tests...
.venv\Scripts\python.exe -m unittest discover -s tests -v
if errorlevel 1 (
    echo [ERROR] Python tests failed.
    goto :FAIL
)

echo [STEP] Running Node tests (optional)...
where node >nul 2>nul
if %errorlevel%==0 (
    node --test nodejs/test/*.test.js
    if errorlevel 1 (
        echo [ERROR] Node tests failed.
        goto :FAIL
    )
    echo [OK] Node tests passed.
) else (
    where winget >nul 2>nul
    if %errorlevel%==0 (
        echo [INFO] Node.js not found. Trying automatic install via winget...
        winget install --id OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements
        if errorlevel 1 (
            echo [WARN] Automatic Node.js install failed or canceled. Skipping Node tests.
            goto :SKIP_NODE
        )
        set "PATH=C:\Program Files\nodejs;%PATH%"
        where node >nul 2>nul
        if %errorlevel%==0 (
            node --test nodejs/test/*.test.js
            if errorlevel 1 (
                echo [ERROR] Node tests failed after installation.
                goto :FAIL
            )
            echo [OK] Node tests passed after installation.
        ) else (
            echo [WARN] Node.js installed but PATH is not refreshed. Open a new terminal and run Node tests later.
        )
    ) else (
        echo [WARN] Node.js not found and winget unavailable. Skipping Node tests.
    )
)

:SKIP_NODE
if "%RUN_QUICKCHECK%"=="1" (
    echo [STEP] Running quick functional check...
    .venv\Scripts\python.exe -c "import runpy; runpy.run_path('scripts/windows_quickcheck.py', run_name='__main__')"
    if errorlevel 1 (
        echo [ERROR] Quick functional check failed.
        goto :FAIL
    )
    echo.
    echo [SUCCESS] Environment setup and validation completed.
    goto :END
)

if "%RUN_SAMPLE_DATA%"=="1" (
    echo [STEP] Generating initial sample data...
    .venv\Scripts\python.exe -c "from datetime import datetime; from reservation_manager import ReservationYamlRepository; ReservationYamlRepository('data').seed_large_test_data(now=datetime.now(), days=30, slots_per_day=4, overwrite=True); print('sample_data_ready=True')"
    if errorlevel 1 (
        echo [ERROR] Failed to generate sample data.
        goto :FAIL
    )
)

if "%RUN_UI%"=="1" (
    echo [STEP] Launching UI server on http://127.0.0.1:5000
    start "" http://127.0.0.1:5000
    .venv\Scripts\python.exe -m reservation_manager.web_app
    if errorlevel 1 (
        echo [ERROR] UI server exited with an error.
        goto :FAIL
    )
    goto :END
)

echo.
echo [SUCCESS] Environment setup completed.
goto :END

:FAIL
echo.
echo [FAILED] %SCRIPT_TITLE% did not complete.
exit /b 1

:END
endlocal
exit /b 0

:detect_python
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY_CMD=py -3"
    exit /b 0
)

where python >nul 2>nul
if %errorlevel%==0 (
    set "PY_CMD=python"
    exit /b 0
)

set "PY_CMD="
exit /b 1

:install_python
set "PYTHON_URL=https://www.python.org/ftp/python/3.11.8/python-3.11.8-amd64.exe"
set "PYTHON_INSTALLER=%TEMP%\python-installer.exe"

echo [INFO] Downloading Python installer...
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_INSTALLER%'}"
if errorlevel 1 (
    echo [ERROR] Failed to download Python installer.
    exit /b 1
)

echo [INFO] Installing Python (this may take a few minutes)...
"%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
if errorlevel 1 (
    echo [ERROR] Failed to install Python.
    del "%PYTHON_INSTALLER%" >nul 2>nul
    exit /b 1
)

del "%PYTHON_INSTALLER%" >nul 2>nul
echo [OK] Python installed successfully.
exit /b 0

:locate_installed_python
REM Try to find python.exe in common installation directories when PATH is stale.
set "PY_SEARCH_RESULT="
for %%D in ("%LOCALAPPDATA%\Programs\Python" "%ProgramFiles%") do (
    if exist "%%~fD" (
        for /f "delims=" %%I in ('dir /b /s /a:-d "%%~fD\Python3*\python.exe" 2^>nul') do (
            if not defined PY_SEARCH_RESULT set "PY_SEARCH_RESULT=%%~I"
        )
    )
)

if defined PY_SEARCH_RESULT (
    set "PY_CMD=""%PY_SEARCH_RESULT%"""
)

exit /b 0
