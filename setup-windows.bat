@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Lecture Atelier: first setup. Downloads Python, PDF tools and local Whisper model.
echo About 0.5-1.5 GB of downloads and 2-4 GB disk. No audio upload. No administrator rights needed.
echo PowerShell may prompt about script policy. We do not disable or bypass it.
powershell.exe -NoProfile -File "%~dp0bootstrap-windows.ps1"
if errorlevel 1 (
  echo Setup did not finish. Read the message above; no recordings were uploaded.
  pause
  exit /b 1
)
call "%~dp0launch-windows.bat"
