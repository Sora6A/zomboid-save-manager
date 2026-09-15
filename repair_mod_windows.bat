@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE="
set "PYTHON_ARGS="

where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3"
    )
)

if not defined PYTHON_EXE (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
        if not errorlevel 1 set "PYTHON_EXE=python"
    )
)

if not defined PYTHON_EXE (
    echo Python 3.10 or newer was not found in PATH.
    pause
    exit /b 1
)

%PYTHON_EXE% %PYTHON_ARGS% install_windows.py --mod-only
if errorlevel 1 goto :failed

echo.
echo Mod repair completed. Restart the game completely before testing.
pause
exit /b 0

:failed
echo.
echo Mod repair failed. Review the messages above.
pause
exit /b 1
