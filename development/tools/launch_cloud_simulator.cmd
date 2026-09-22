@echo off
setlocal
cd /d "%~dp0..\.."
if not exist ".venv\Scripts\python.exe" (
  echo Install the desktop dependencies described in development\simulator\README.md first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" development\tools\run_simulator.py --cloud
if errorlevel 1 pause
