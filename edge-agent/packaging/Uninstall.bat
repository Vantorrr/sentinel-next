@echo off
cd /d "%~dp0"
schtasks /End /TN \SentinelEdge
schtasks /Delete /TN \SentinelEdge /F
echo Task removed. Config, queue and logs in %%ProgramData%%\SentinelEdge were kept.
echo To delete them too, remove that folder yourself.
pause
