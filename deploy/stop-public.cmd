@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-public.ps1" -Stop
echo.
pause
