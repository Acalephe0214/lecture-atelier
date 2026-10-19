@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -File "%~dp0bootstrap-windows.ps1" %*
if errorlevel 1 (
  echo Setup did not finish. Read the message above; no recordings were uploaded.
  pause
  exit /b 1
)
exit /b 0
