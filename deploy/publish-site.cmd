@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish-site.ps1" %*
echo.
pause
