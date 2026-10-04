@echo off
rem MME Ombor ni shu papkadan kompyuterga o'rnatadi (internet kerak emas).
rem Ixtiyoriy: Ornatish.bat [o'rnatish papkasi] [yorliq qo'yiladigan papka]
chcp 65001 >nul
setlocal

set "SOURCE=%~dp0."
set "TARGET=%~1"
if "%TARGET%"=="" set "TARGET=%LOCALAPPDATA%\Programs\MME-Ombor"
set "SHORTCUTS=%~2"

if not exist "%SOURCE%\MME-Ombor.exe" (
    echo XATO: MME-Ombor.exe shu papkada topilmadi.
    pause
    exit /b 1
)

echo MME Ombor o'rnatilmoqda: %TARGET%
robocopy "%SOURCE%" "%TARGET%" /E /NFL /NDL /NJH /NJS /NP /XF Ornatish.bat >nul
if errorlevel 8 (
    echo XATO: fayllarni nusxalab bo'lmadi.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$folder = if ($env:SHORTCUTS) { $env:SHORTCUTS } else { [Environment]::GetFolderPath('Desktop') };" ^
    "$link = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $folder 'MME Ombor.lnk'));" ^
    "$link.TargetPath = Join-Path $env:TARGET 'MME-Ombor.exe'; $link.WorkingDirectory = $env:TARGET; $link.Save()"
if errorlevel 1 echo Ogohlantirish: ish stoliga yorliq qo'yib bo'lmadi. Dastur: %TARGET%\MME-Ombor.exe

echo.
echo Tayyor. Ish stolidagi "MME Ombor" yorlig'ini oching.
pause
