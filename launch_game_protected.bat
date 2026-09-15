@echo off
setlocal

set "ZSM_EXE=%LOCALAPPDATA%\ZomboidSaveManager\ZomboidSaveManager.exe"
if not exist "%ZSM_EXE%" (
    echo Installed companion was not found:
    echo %ZSM_EXE%
    echo Run setup_windows.bat first.
    pause
    exit /b 1
)

start "" "%ZSM_EXE%" --launch-game --minimized --exit-with-game
exit /b 0
