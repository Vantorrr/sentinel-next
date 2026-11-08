@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m sentinel_edge.cli status --config "%ProgramData%\SentinelEdge\config.env"
) else (
  py -3 -m sentinel_edge.cli status --config "%ProgramData%\SentinelEdge\config.env"
)
pause
