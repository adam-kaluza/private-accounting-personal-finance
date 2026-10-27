@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
if not exist "%~dp0runtime\pythonw.exe" (
  echo Please extract the entire ZIP before starting Private Accounting.
  pause
  exit /b 1
)
start "" "%~dp0runtime\pythonw.exe" "%~dp0app\launch.py"
exit /b 0
