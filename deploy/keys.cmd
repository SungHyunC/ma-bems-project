@echo off
cd /d "%~dp0.."
".venv\Scripts\python.exe" server\mabems_server.py --list-keys --show
echo.
echo   new key : .venv\Scripts\python.exe server\mabems_server.py --new-key NAME   (add --admin to allow Claude)
echo   revoke  : .venv\Scripts\python.exe server\mabems_server.py --revoke NAME
echo.
pause
