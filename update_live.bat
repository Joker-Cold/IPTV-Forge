@echo off
rem One-click live update: run iptv_api once, regroup, copy to ..\HK-IPTV
rem Flags pass through to live\update_live.py, e.g.  update_live.bat --no-docker
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
python live\update_live.py %*
echo.
pause
