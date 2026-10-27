@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
"%~dp0runtime\python.exe" "%~dp0tools\run_tests.py"
if errorlevel 1 (
  echo Tests failed. See the messages above.
) else (
  echo All fictional tests passed. No personal records were used.
)
pause
