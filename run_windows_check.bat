@echo off
setlocal EnableExtensions

echo ==================================================
echo Reservation Manager - Windows One-Click Check
echo ==================================================
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
        goto :FAIL
    )
)

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
.venv\Scripts\python.exe -m pip install PyYAML >nul
if errorlevel 1 (
    echo [ERROR] Failed to install PyYAML.
    goto :FAIL
)
echo [OK] Python dependencies installed.

echo [STEP] Running Python tests...
.venv\Scripts\python.exe -m unittest discover -s tests -v
if errorlevel 1 (
    echo [ERROR] Python tests failed.
    goto :FAIL
)
echo [OK] Python tests passed.

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
echo [STEP] Running quick functional check...
.venv\Scripts\python.exe -c "import runpy; runpy.run_path('scripts/windows_quickcheck.py', run_name='__main__')"
if errorlevel 1 (
    echo [ERROR] Quick functional check failed.
    goto :FAIL
)
echo [OK] Quick functional check passed.

echo.
echo [SUCCESS] Environment setup and validation completed.
echo [INFO] Check generated files under data\*.yaml
goto :END

:FAIL
echo.
echo [FAILED] One-click check did not complete.
exit /b 1

:END
endlocal
exit /b 0
