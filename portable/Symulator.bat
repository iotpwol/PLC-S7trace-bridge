@echo off
rem Lokalny symulator PLC (127.0.0.1:1102) do prob bez sterownika.
cd /d "%~dp0"
"python\python.exe" -m s7trace.sim
pause
