@echo off
rem Uruchomienie z oknem konsoli - pokazuje bledy, ktorych S7Trace.bat nie wyswietla.
cd /d "%~dp0"
"python\python.exe" "app\main.py"
echo.
echo Program zakonczyl dzialanie (kod %errorlevel%).
pause
