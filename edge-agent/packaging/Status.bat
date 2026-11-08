@echo off
chcp 65001 >nul
if not exist "%ProgramData%\SentinelEdge\status.json" (
  echo No status yet. The boot task may still be starting.
  pause
  exit /b 1
)
type "%ProgramData%\SentinelEdge\status.json"
echo.
pause
