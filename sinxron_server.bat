@echo off
rem Markaziy sinxronlash serveri: barcha kompyuterlar uchun yagona baza (README: «Markaziy server»).
rem Kirish kaliti OMBOR_SYNC_TOKEN dan olinadi; berilmagan bo'lsa, so'raladi. Port: 8765.
setlocal
cd /d "%~dp0"

set PYTHON=python
if exist .venv\Scripts\python.exe set PYTHON=.venv\Scripts\python

if "%OMBOR_SYNC_TOKEN%"=="" set /p OMBOR_SYNC_TOKEN=Kirish kaliti (kamida 8 belgi):
%PYTHON% -m ombor.sync_server --port 8765 --data ombor-server.db
