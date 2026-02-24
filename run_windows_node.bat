@echo off
setlocal EnableExtensions

echo ================================================
echo Reservation Manager - Node.js Runner
echo ================================================
echo.

cd /d "%~dp0"

set "MODE=%~1"
if /I "%MODE%"=="" set "MODE=test"

set "NODE_EXE="
where node >nul 2>nul
if %errorlevel%==0 (
    set "NODE_EXE=node"
) else (
    if exist "C:\Program Files\nodejs\node.exe" (
        set "NODE_EXE=C:\Program Files\nodejs\node.exe"
    ) else (
        echo [ERROR] Node.js not found.
        echo [INFO] Install Node.js LTS: https://nodejs.org/
        echo [INFO] After install, open a new terminal and run this file again.
        exit /b 1
    )
)

if /I "%MODE%"=="test" goto :RUN_TEST
if /I "%MODE%"=="server" goto :RUN_SERVER
if /I "%MODE%"=="all" goto :RUN_ALL

echo [ERROR] Invalid mode: %MODE%
echo [INFO] Usage:
echo   run_windows_node.bat            ^(default: test^)
echo   run_windows_node.bat test       ^(run node tests^)
echo   run_windows_node.bat server     ^(start node api server^)
echo   run_windows_node.bat all        ^(test then start server^)
exit /b 1

:RUN_TEST
echo [STEP] Running Node.js tests...
"%NODE_EXE%" --test nodejs/test/*.test.js
if errorlevel 1 (
    echo [ERROR] Node.js tests failed.
    exit /b 1
)
echo [SUCCESS] Node.js tests passed.
goto :END

:RUN_SERVER
echo [STEP] Starting Node.js API server...
echo [INFO] URL: http://127.0.0.1:3000
start "" http://127.0.0.1:3000
"%NODE_EXE%" nodejs/server.js
if errorlevel 1 (
    echo [ERROR] Node.js server failed to start.
    exit /b 1
)
goto :END

:RUN_ALL
call "%~f0" test
if errorlevel 1 exit /b 1
call "%~f0" server
if errorlevel 1 exit /b 1

:END
endlocal
exit /b 0
