@echo off
rem MME Ombor ni kompyuterdan o'chiradi (ma'lumotlar bazasi va zaxira nusxalar saqlanib qoladi).
rem Skript dastur papkasining o'zida turadi, shuning uchun vaqtinchalik papkaga ko'chirib ishga tushiriladi;
rem hammasi bitta qatorda: bu fayl o'chirilgach, cmd undan keyingi qatorni o'qiy olmaydi.
copy /y "%~dp0Ochirish.ps1" "%TEMP%\MME-Ombor-Ochirish.ps1" >nul & powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\MME-Ombor-Ochirish.ps1" -Target "%~dp0." %* & exit /b
