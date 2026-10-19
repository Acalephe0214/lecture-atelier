@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0.portable\vendor;%PYTHONPATH%"
if exist "%~dp0.portable\python\python.exe" (
  "%~dp0.portable\python\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
  if not errorlevel 1 (
    "%~dp0.portable\python\python.exe" bootstrap.py --configure-bundled
    "%~dp0.portable\python\python.exe" app.py --open
    if errorlevel 1 pause
    exit /b
  )
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
  if not errorlevel 1 (
    py -3 bootstrap.py --configure-bundled
    py -3 app.py --open
    if errorlevel 1 pause
    exit /b
  )
)
where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
  if not errorlevel 1 (
    python bootstrap.py --configure-bundled
    python app.py --open
    if errorlevel 1 pause
    exit /b
  )
)
powershell.exe -NoProfile -File "%~dp0bootstrap-windows.ps1" -Profile basic
if errorlevel 1 pause

