@echo off
rem Build IPTV-Forge.exe into the repo root - the logic is in build_exe.py.
rem Needs: pip install pyinstaller pywebview. Add --zip for the release package.
cd /d "%~dp0.."
python gui\build_exe.py %*
pause
