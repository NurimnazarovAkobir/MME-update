@echo off
rem MME Ombor ni shu papkadan kompyuterga o'rnatadi (internet kerak emas).
rem Asosiy ish Ornatish.ps1 da; bu fayl uni ikki marta bosish bilan ishga tushirish uchun.
rem Ixtiyoriy: Ornatish.bat -Target "papka" -ShortcutFolder "papka" -RegistryName "nom" -Quiet
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Ornatish.ps1" %*
exit /b %errorlevel%
