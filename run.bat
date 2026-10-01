@echo off
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"

rem .venv skopiowany z innego komputera wskazuje na nieistniejacego Pythona -> odtworz go
if exist ".venv\pyvenv.cfg" (
  set "VHOME="
  for /f "tokens=1,* delims== " %%a in (.venv\pyvenv.cfg) do if /i "%%a"=="home" set "VHOME=%%b"
  if not exist "%VHOME%\python.exe" (
    echo Srodowisko .venv pochodzi z innego komputera - tworze je od nowa...
    rmdir /s /q .venv
  )
)

if not exist "%PY%" (
  where py >nul 2>&1
  if not errorlevel 1 (
    py -3 -m venv .venv
  ) else (
    python -m venv .venv
  )
  if not exist "%PY%" (
    echo.
    echo Nie znaleziono Pythona 3. Zainstaluj go z https://www.python.org/downloads/ i uruchom ponownie.
    pause
    exit /b 1
  )
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo Instalacja bibliotek nie powiodla sie ^(brak internetu albo zbyt dluga sciezka katalogu - trzymaj program blisko korzenia dysku, np. C:\Dev\S7trace^).
    rmdir /s /q .venv
    pause
    exit /b 1
  )
)

start "" ".venv\Scripts\pythonw.exe" main.py
