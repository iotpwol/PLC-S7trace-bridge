@echo off
cd /d "%~dp0"
if not exist "python\pythonw.exe" (
  echo Brak python\pythonw.exe - rozpakuj caly folder S7Trace, nie pojedyncze pliki.
  pause
  exit /b 1
)
start "" "python\pythonw.exe" "app\main.py"
