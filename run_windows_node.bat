@echo off
setlocal EnableExtensions

echo ================================================
echo Reservation Manager - Node.js Runner
echo ================================================
echo.

cd /d "%~dp0"

set "MODE=%~1"
if /I "%MODE%"=="" set "MODE=all"

set "WORKSPACE=%CD%"
set "NODE_VERSION=20.12.2"
set "NODE_DIST=node-v%NODE_VERSION%-win-x64"
set "NODE_RUNTIME_DIR=%WORKSPACE%\.node_runtime"
set "LOCAL_NODE_EXE=%NODE_RUNTIME_DIR%\%NODE_DIST%\node.exe"
set "PY_HELPER=%WORKSPACE%\run_windows_python.bat"
set "NODE_EXE="
set "EXIT_CODE=0"

call :ensure_node_runtime
if errorlevel 1 (
    set "EXIT_CODE=1"
    goto :finish
)

call :ensure_python_backend
if errorlevel 1 (
    set "EXIT_CODE=1"
    goto :finish
)

if /I "%MODE%"=="setup" goto :finish
if /I "%MODE%"=="test" goto :run_tests_only
if /I "%MODE%"=="server" goto :run_server_only
if /I "%MODE%"=="all" goto :run_all

:usage
echo [USAGE] run_windows_node.bat [setup^|test^|server^|all]
echo         default mode is 'all' which installs deps, runs tests, then launches the Node API server.
set "EXIT_CODE=1"
goto :finish

:run_tests_only
call :run_python_tests
if errorlevel 1 (
    set "EXIT_CODE=1"
    goto :finish
)
call :run_node_tests
set "EXIT_CODE=%ERRORLEVEL%"
goto :finish

:run_server_only
call :launch_node_server
set "EXIT_CODE=%ERRORLEVEL%"
goto :finish

:run_all
call :run_python_tests
if errorlevel 1 (
    set "EXIT_CODE=1"
    goto :finish
)
call :run_node_tests
if errorlevel 1 (
    set "EXIT_CODE=1"
    goto :finish
)
call :launch_node_server
set "EXIT_CODE=%ERRORLEVEL%"
goto :finish

:ensure_node_runtime
call :detect_node
if defined NODE_EXE (
    echo [OK] Node.js found: %NODE_EXE%
    exit /b 0
)

echo [WARN] Node.js not found. Attempting portable installation (v%NODE_VERSION%)...
call :install_node_runtime
if errorlevel 1 exit /b 1
call :detect_node
if not defined NODE_EXE (
    echo [ERROR] Node.js installation completed but executable not located.
    exit /b 1
)
echo [OK] Node.js installed locally at %NODE_EXE%
exit /b 0

:detect_node
if exist "%LOCAL_NODE_EXE%" (
    set "NODE_EXE=%LOCAL_NODE_EXE%"
    exit /b 0
)

where node >nul 2>nul
if %errorlevel%==0 (
    set "NODE_EXE=node"
    exit /b 0
)

if exist "C:\Program Files\nodejs\node.exe" (
    set "NODE_EXE=C:\Program Files\nodejs\node.exe"
    exit /b 0
)

set "NODE_EXE="
exit /b 1

:install_node_runtime
set "NODE_ARCHIVE=%TEMP%\node-runtime.zip"
set "NODE_URL=https://nodejs.org/dist/v%NODE_VERSION%/%NODE_DIST%.zip"

if exist "%NODE_RUNTIME_DIR%" rd /s /q "%NODE_RUNTIME_DIR%" >nul 2>nul
mkdir "%NODE_RUNTIME_DIR%" >nul 2>nul

echo [INFO] Downloading Node.js runtime from %NODE_URL%
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%NODE_URL%' -OutFile '%NODE_ARCHIVE%'}"
if errorlevel 1 (
    echo [ERROR] Failed to download Node.js runtime.
    del "%NODE_ARCHIVE%" >nul 2>nul
    exit /b 1
)

echo [INFO] Extracting Node.js runtime...
powershell -Command "& {Expand-Archive -LiteralPath '%NODE_ARCHIVE%' -DestinationPath '%NODE_RUNTIME_DIR%' -Force}"
if errorlevel 1 (
    echo [ERROR] Failed to extract Node.js runtime.
    del "%NODE_ARCHIVE%" >nul 2>nul
    exit /b 1
)

del "%NODE_ARCHIVE%" >nul 2>nul
exit /b 0

:ensure_python_backend
if not exist "%PY_HELPER%" (
    echo [ERROR] Missing helper script: %PY_HELPER%
    exit /b 1
)
echo [STEP] Ensuring Python backend prerequisites...
call "%PY_HELPER%" setup
if errorlevel 1 (
    echo [ERROR] Python backend preparation failed.
    exit /b 1
)
exit /b 0

:run_python_tests
echo [STEP] Running Python unit tests before Node startup...
call "%PY_HELPER%" test
if errorlevel 1 (
    echo [ERROR] Python unit tests failed.
    exit /b 1
)
exit /b 0

:run_node_tests
echo [STEP] Running Node.js tests...
"%NODE_EXE%" --test nodejs/test/*.test.js
if errorlevel 1 (
    echo [ERROR] Node.js tests failed.
    exit /b 1
)
echo [SUCCESS] Node.js tests passed.
exit /b 0

:launch_node_server
echo [STEP] Starting Node.js API server...
echo [INFO] URL: http://127.0.0.1:3000
set "PYTHON_EXE=%WORKSPACE%\.venv\Scripts\python.exe"
set "PYTHONPATH=%WORKSPACE%"
start "" http://127.0.0.1:3000
"%NODE_EXE%" nodejs/server.js
exit /b %errorlevel%

:finish
endlocal & exit /b %EXIT_CODE%
