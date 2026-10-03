@echo off
rem Test zapisu i odczytu do TimescaleDB / PostgreSQL (np. na Windows Server 2016).
rem Pyta o adres serwera i haslo, sprawdza oba sterowniki (psycopg, pg8000) i zapisuje
rem raport w diagnoza_timescale.txt obok tego pliku (haslo NIE trafia do raportu).
cd /d "%~dp0"
"python\python.exe" "app\diagnoza_timescale.py"
echo.
pause
