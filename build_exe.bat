@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE="
set "PYTHON_ARGS="
set "VENV_PYTHON=.venv\Scripts\python.exe"

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
    if /i not "%~1"=="--no-pause" pause
    exit /b 1
)

if exist "%VENV_PYTHON%" (
    call :validate_venv
    if errorlevel 1 (
        echo The existing .venv is incomplete or incompatible. Rebuilding it...
        call :rebuild_venv
        if errorlevel 1 goto :failed
    )
) else (
    call :rebuild_venv
    if errorlevel 1 goto :failed
)

"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto :failed
"%VENV_PYTHON%" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :failed

"%VENV_PYTHON%" -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name ZomboidSaveManager ^
  --hidden-import psutil ^
  start.pyw
if errorlevel 1 goto :failed

echo.
echo Build completed: dist\ZomboidSaveManager.exe
if /i not "%~1"=="--no-pause" pause
exit /b 0

:validate_venv
if not exist "%VENV_PYTHON%" exit /b 1
"%VENV_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 exit /b 1
"%VENV_PYTHON%" -m pip --version >nul 2>nul
if not errorlevel 1 exit /b 0
echo pip is missing from .venv. Attempting repair with ensurepip...
"%VENV_PYTHON%" -m ensurepip --upgrade
if errorlevel 1 exit /b 1
"%VENV_PYTHON%" -m pip --version >nul 2>nul
if errorlevel 1 exit /b 1
exit /b 0

:rebuild_venv
echo Creating a clean Python virtual environment...
"%PYTHON_EXE%" %PYTHON_ARGS% -m venv --clear ".venv"
if not exist "%VENV_PYTHON%" exit /b 1
call :validate_venv
if errorlevel 1 exit /b 1
exit /b 0

:failed
echo.
echo Build failed. Review the error messages above.
if /i not "%~1"=="--no-pause" pause
exit /b 1
