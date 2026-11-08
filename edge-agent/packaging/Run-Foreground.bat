@echo off
setlocal
chcp 65001 >nul
if "%~1"=="" goto :usage
if not exist "%~f1" (
  echo Config file was not found. Pass the full path of the salon config.
  exit /b 2
)

set "HERE=%~dp0"
for %%I in ("%HERE%.") do set "ROOT=%%~fI"
if not exist "%ROOT%\sentinel_edge\cli.py" for %%I in ("%ROOT%\..") do set "ROOT=%%~fI"
if exist "%ROOT%\sitecustomize.py" goto :refuse
if exist "%ROOT%\usercustomize.py" goto :refuse
if exist "%ROOT%\.venv\" goto :refuse

set "PY="
where py >nul 2>&1 && for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)"') do set "PY=%%P"
if not defined PY goto :nopy
echo %PY% | findstr /I /C:"\.venv\\" /C:"\SentinelEdge\app\\" >nul && goto :refuse

set "PYTHONPATH=%ROOT%"
set "PYTHONSAFEPATH=1"
echo Starting foreground agent. No administrator prompt and no boot task.
echo Success is decoded_frames greater than 0 and event_http=200.
echo opened is not printed and is not a decoded frame.
"%PY%" -P -m sentinel_edge.cli run --config "%~f1"
exit /b %ERRORLEVEL%

:usage
echo Usage: Run-Foreground.bat C:\path\to\config.env
echo The config file is not printed. Put the salon RTSP URLs only in that file.
exit /b 2

:nopy
echo Python 3.11+ was not found with py -3.
echo Install Python yourself. This window does not download it and does not elevate.
exit /b 2

:refuse
echo Refusing to start.
echo The package folder contains sitecustomize.py, usercustomize.py, or .venv,
echo or py -3 points at an existing Sentinel venv.
echo This launcher does not run that Python and does not request administrator.
exit /b 3
