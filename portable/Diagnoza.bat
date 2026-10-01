@echo off
rem Diagnostyka: sprawdza Windows, biblioteki systemowe wymagane przez Qt i kompletnosc plikow.
rem Wynik jest zapisywany w diagnoza.txt obok tego pliku.
cd /d "%~dp0"
"python\python.exe" "app\diagnoza.py"
echo.
pause
