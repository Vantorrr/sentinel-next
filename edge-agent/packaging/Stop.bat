@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m sentinel_edge.cli stop --config "%ProgramData%\SentinelEdge\config.env"
) else (
  py -3 -m sentinel_edge.cli stop --config "%ProgramData%\SentinelEdge\config.env"
)
schtasks /End /TN \SentinelEdge
echo Stop requested.
pause
