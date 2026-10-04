@echo off
rem Mijozga beriladigan to'plamni yig'adi: dist\ (MME-Ombor.exe, Ornatish.bat, OQING.txt)
setlocal
cd /d "%~dp0"

if not exist .venv (
    python -m venv .venv || exit /b 1
)
.venv\Scripts\python -m pip install --quiet --disable-pip-version-check -r requirements.txt || exit /b 1

if not exist build mkdir build
.venv\Scripts\python -m ombor.ui.icon build\icon.ico || exit /b 1

.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name MME-Ombor --icon build\icon.ico main.py || exit /b 1

rem O'rnatish skripti va yo'riqnoma: dist papkasi mijozga beriladigan to'plam bo'ladi.
copy /y toplam\* dist\ >nul || exit /b 1

echo.
echo Tayyor: dist\MME-Ombor.exe
