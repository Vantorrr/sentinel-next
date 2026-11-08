@echo off
chcp 65001 >nul
set "HERE=%~dp0"
for %%I in ("%HERE%.") do set "ROOT=%%~fI"
if not exist "%ROOT%\sentinel_edge\cli.py" for %%I in ("%ROOT%\..") do set "ROOT=%%~fI"
cd /d "%ROOT%"

net session >nul 2>&1
if errorlevel 1 (
  echo Administrator approval is required once to register the boot task.
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs -WorkingDirectory '%ROOT%'"
  exit /b
)

set "PYEXE=%ProgramFiles%\Python312\python.exe"
if not exist "%PYEXE%" (
  echo Installing Python 3.12 for all users into Program Files.
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe' -OutFile \"$env:TEMP\python-setup.exe\""
  if errorlevel 1 goto :fail
  "%TEMP%\python-setup.exe" /quiet InstallAllUsers=1 PrependPath=0 Include_pip=1 Include_test=0 TargetDir="%ProgramFiles%\Python312"
  if errorlevel 1 goto :fail
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
