@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (py -3 app.py %*) || (python app.py %*)
if errorlevel 1 (
  echo.
  echo [!] เปิดโปรแกรมไม่ได้ - ตรวจสอบว่าติดตั้ง Python 3 แล้ว: https://www.python.org/downloads/
  echo     ตอนติดตั้งให้ติ๊ก "Add python.exe to PATH"
)
pause
