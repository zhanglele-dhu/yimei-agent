@echo off
setlocal
title Shop Photo Assistant
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
chcp 65001 >nul
echo Starting... Please keep this window open.
if not exist ".venv-studio\Scripts\python.exe" (
  echo ERROR: Python environment missing. See DEPLOYMENT.md.
  pause
  exit /b 1
)
".venv-studio\Scripts\python.exe" -u run_studio.py
echo.
echo Server stopped. If an error appears above, copy it for troubleshooting.
pause
