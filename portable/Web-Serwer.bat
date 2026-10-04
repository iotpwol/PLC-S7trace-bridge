@echo off
rem Serwer trybu Web: wspolne polaczenia ze sterownikami, wielu uzytkownikow w przegladarkach.
rem Uzycie: Web-Serwer.bat [plik_konfiguracji.json] ; adres w sieci: dopisz  --host 0.0.0.0
rem Pierwsze konto (administrator) tworzy sie w przegladarce. Opis: WEB.md
cd /d "%~dp0"
set CFG=%1
if "%CFG%"=="" (
  "python\python.exe" -m s7trace.web --host 0.0.0.0 --tls
) else (
  "python\python.exe" -m s7trace.web --config %CFG% --host 0.0.0.0 --tls
)
pause
