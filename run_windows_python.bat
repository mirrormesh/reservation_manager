@echo off
setlocal EnableExtensions

echo ================================================
echo Reservation Manager - Windows UI Runner
echo ================================================
echo.

cd /d "%~dp0"
set "PYTHONPATH=%CD%"

set "MODE=%~1"
if /I "%MODE%"=="" set "MODE=all"

set "PY_CMD="
set "VENV_DIR=%CD%\.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "EXIT_CODE=0"

if /I "%MODE%"=="help" goto :usage

call :prepare_environment
if errorlevel 1 (
    set "EXIT_CODE=1"
    goto :finish
)

if /I "%MODE%"=="setup" (
    echo [SUCCESS] Python environment is ready.
    goto :finish
)

if /I "%MODE%"=="test" goto :run_tests_only
if /I "%MODE%"=="server" goto :run_server_only
if /I "%MODE%"=="all" goto :run_all

:usage
echo [USAGE] run_windows_python.bat [setup^|test^|server^|all]
echo         default mode is 'all' which prepares env, runs tests, then launches the UI server.
set "EXIT_CODE=1"
goto :finish

:run_tests_only
call :run_tests
set "EXIT_CODE=%ERRORLEVEL%"
goto :finish

:run_server_only
call :launch_server
set "EXIT_CODE=%ERRORLEVEL%"
goto :finish

:run_all
call :run_tests
if errorlevel 1 (
    set "EXIT_CODE=1"
    goto :finish
)
call :launch_server
set "EXIT_CODE=%ERRORLEVEL%"
goto :finish

:prepare_environment
call :detect_python
if not defined PY_CMD (
    echo [WARN] Python 3 is not installed.
    echo [INFO] Attempting automatic install of Python 3.11...
    call :install_python
    if errorlevel 1 (
        echo [ERROR] Automatic Python installation failed.
        exit /b 1
    )
    call :detect_python
    if not defined PY_CMD call :locate_installed_python
    if not defined PY_CMD (
        echo [ERROR] Python installation finished but interpreter not found.
        echo [INFO] Please restart this terminal or install Python 3.9+ from https://www.python.org/downloads/windows/
        exit /b 1
    )
)

echo [OK] Python found: %PY_CMD%
if not exist "%VENV_PY%" (
    echo [STEP] Preparing virtual environment...
    %PY_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        exit /b 1
    )
)

echo [STEP] Installing dependencies...
"%VENV_PY%" -m pip install --upgrade pip >nul
"%VENV_PY%" -m pip install PyYAML Flask holidays >nul
if errorlevel 1 (
    echo [ERROR] Failed to install Python dependencies.
    exit /b 1
)

call :ensure_test_data
if errorlevel 1 (
    echo [ERROR] Failed to ensure sample test data.
    exit /b 1
)

echo [OK] Python workspace prepared.
exit /b 0

:run_tests
echo [STEP] Running Python unit tests...
"%VENV_PY%" -m unittest discover -s tests -v
if errorlevel 1 (
    echo [ERROR] Python unit tests failed.
    exit /b 1
)
echo [SUCCESS] Python unit tests passed.
exit /b 0

:launch_server
echo [STEP] Launching UI server on http://127.0.0.1:5000
start "" http://127.0.0.1:5000
"%VENV_PY%" -c "from reservation_manager.web_app import create_app; app=create_app(); app.run(host='127.0.0.1', port=5000, debug=False)"
exit /b %errorlevel%

:ensure_test_data
set "NEED_SEED=0"
if not exist "data\active_reservations.yaml" set "NEED_SEED=1"
if "%NEED_SEED%"=="0" (
    for %%F in ("data\active_reservations.yaml" "data\closed_reservations.yaml") do (
        if exist "%%~fF" (
            for %%S in ("%%~fF") do if %%~zS EQU 0 set "NEED_SEED=1"
        ) else (
            set "NEED_SEED=1"
        )
    )
)

if "%NEED_SEED%"=="0" (
    echo [INFO] Existing sample data detected. Skipping generation.
    exit /b 0
)

echo [STEP] Generating initial sample data...
"%VENV_PY%" -c "from datetime import datetime; from reservation_manager import ReservationYamlRepository; ReservationYamlRepository('data').seed_large_test_data(now=datetime.now(), days=30, slots_per_day=4, overwrite=True); print('sample_data_ready=True')"
if errorlevel 1 (
    echo [ERROR] Sample data generation failed.
    exit /b 1
)

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
    set "PY_CMD=""%PY_SEARCH_RESULT%""
)

exit /b 0

:finish
endlocal & exit /b %EXIT_CODE%
