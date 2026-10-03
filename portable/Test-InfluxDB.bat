@echo off
rem Test zapisu, odczytu i USUWANIA w InfluxDB 1.x / 2.x (np. na serwerze produkcyjnym).
rem Pyta o wersje, adres i dane logowania; dane testowe maja wlasny pomiar i sa na koncu usuwane.
rem Raport: diagnoza_influx.txt obok tego pliku (token i haslo NIE trafiaja do raportu).
cd /d "%~dp0"
"python\python.exe" "app\diagnoza_influx.py"
echo.
pause
