@echo off
setlocal
cd /d "%~dp0"

call build_exe.bat --no-pause
if errorlevel 1 goto :failed

".venv\Scripts\python.exe" install_windows.py
if errorlevel 1 goto :failed

echo.
echo Setup completed. Enable "Zomboid Save Manager Bridge" once in the game's Mods menu.
pause
exit /b 0

:failed
echo.
echo Setup failed. Review the messages above.
pause
exit /b 1
