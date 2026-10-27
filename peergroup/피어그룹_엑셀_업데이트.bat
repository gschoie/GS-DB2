@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "update_peergroup_excel.ps1"
echo.
pause
