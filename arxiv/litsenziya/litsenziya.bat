@echo off
rem Litsenziya berish dasturini ochadi (faqat sotuvchi uchun).
cd /d "%~dp0.."
start "" .venv\Scripts\pythonw.exe sotuvchi\litsenziya.py
