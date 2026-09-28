@echo off
rem Install JARVIS: run installer\install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
