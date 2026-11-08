@echo off
if not exist "%ProgramData%\SentinelEdge\control" mkdir "%ProgramData%\SentinelEdge\control"
echo stop> "%ProgramData%\SentinelEdge\control\stop.request"
schtasks /End /TN \SentinelEdge
echo Stop requested. Config was not deleted.
pause
