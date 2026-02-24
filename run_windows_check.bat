@echo off
REM Backward-compatible shim: delegate to the unified setup script.
call "%~dp0run_windows_first_run.bat" check %*
exit /b %errorlevel%
