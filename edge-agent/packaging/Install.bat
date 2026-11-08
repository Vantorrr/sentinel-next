@echo off
chcp 65001 >nul
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  echo Administrator approval is required once to register the boot task.
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs -WorkingDirectory '%~dp0'"
  exit /b
)

set "PYEXE="
where py >nul 2>&1 && py -3 -c "import sys" >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PYEXE=%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PYEXE where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE (
  echo Installing Python 3.12 for the current user.
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe' -OutFile \"$env:TEMP\python-setup.exe\""
  if errorlevel 1 goto :fail
  "%TEMP%\python-setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_test=0
  set "PYEXE=%LocalAppData%\Programs\Python\Python312\python.exe"
)

set "PYTHONPATH=%~dp0"
%PYEXE% -m sentinel_edge.install_win install --root "%~dp0"
if errorlevel 1 goto :fail
echo Install finished. The task SentinelEdge is visible in Task Scheduler.
pause
exit /b 0

:fail
echo Install failed. Photograph this window.
pause
exit /b 1
