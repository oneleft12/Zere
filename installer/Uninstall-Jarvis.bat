@echo off
rem Uninstall JARVIS: run installer\uninstall.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1" %*
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
