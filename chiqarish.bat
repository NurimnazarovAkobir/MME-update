@echo off
rem Yangi versiyani bitta buyruq bilan chiqaradi: versiyani oshiradi, testlaydi, yig'adi va tarqatadi.
rem Ishlatish: chiqarish.bat            (versiya o'zi oshadi: 1.4 -^> 1.5)
rem            chiqarish.bat 2.0        (aniq versiya)
rem            chiqarish.bat --testsiz  (testlarsiz, tezroq)
cd /d "%~dp0"
.venv\Scripts\python -m tools.chiqarish %*
echo.
pause
