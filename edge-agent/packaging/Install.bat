@echo off
chcp 65001 >nul
set "HERE=%~dp0"
for %%I in ("%HERE%.") do set "ROOT=%%~fI"
if not exist "%ROOT%\sentinel_edge\cli.py" for %%I in ("%ROOT%\..") do set "ROOT=%%~fI"
cd /d "%ROOT%"

echo This elevated installer is not the salon camera check.
echo For a decoded frame and server ACK, close this window and run Run-Foreground.bat.
echo.

net session >nul 2>&1
if errorlevel 1 (
  echo Administrator approval is required once to register the boot task.
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs -WorkingDirectory '%ROOT%'"
  exit /b
)

set "PYEXE=%ProgramFiles%\Python312\python.exe"
if not exist "%PYEXE%" (
  echo Python 3.12 for all users is not installed in %%ProgramFiles%%\Python312.
  echo This installer does not download Python.
  echo Use Run-Foreground.bat with the Python already on this PC.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Assert-TrustedRoot.ps1" -Root "%ROOT%"
if errorlevel 1 goto :fail

set "PYTHONPATH=%ROOT%"
"%PYEXE%" -m sentinel_edge.install_win install --root "%ROOT%"
if errorlevel 1 goto :fail
echo Install finished. Task SentinelEdge is visible in Task Scheduler.
echo The running copy is under %%ProgramData%%\SentinelEdge\app, not this folder.
pause
exit /b 0

:fail
echo Install failed. Photograph this window.
pause
exit /b 1
