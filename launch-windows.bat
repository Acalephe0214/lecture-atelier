@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0.portable\vendor;%PYTHONPATH%"
if exist "%~dp0.portable\python\python.exe" (
  "%~dp0.portable\python\python.exe" bootstrap.py --configure-bundled
  "%~dp0.portable\python\python.exe" app.py --open
  if errorlevel 1 pause
  exit /b
)
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 app.py --open
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    call "%~dp0setup-windows.bat"
    exit /b
  )
  python app.py --open
)
if errorlevel 1 (
  echo 请确认已安装 Python 3.10 或以上，并检查上方提示。
  pause
)

