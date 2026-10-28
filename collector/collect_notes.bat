@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist ".venv-collector\Scripts\python.exe" (
    echo Collector environment missing. See COLLECTOR_README.md.
    pause
    exit /b 1
)
".venv-collector\Scripts\python.exe" collect_notes.py %*
pause
