@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

set MODEL=dumping_sites_fasterrcnn.pt
set IMAGES_DIR=images
set RESULTS_DIR=results

if exist "%MODEL%" goto check_script
echo ไม่พบไฟล์โมเดล %MODEL% ในโฟลเดอร์นี้
echo ตรวจสอบว่าเอา dumping_sites_fasterrcnn.pt มาวางไว้โฟลเดอร์เดียวกับสคริปต์นี้แล้ว
pause
exit /b 1

:check_script
if exist "infer_detector.py" goto make_dir
echo ไม่พบไฟล์ infer_detector.py ในโฟลเดอร์นี้
pause
exit /b 1

:make_dir
if not exist "%IMAGES_DIR%" mkdir "%IMAGES_DIR%"

dir /b "%IMAGES_DIR%\*.jpg" "%IMAGES_DIR%\*.jpeg" "%IMAGES_DIR%\*.png" >nul 2>&1
if errorlevel 1 goto no_images
goto run_detect

:no_images
echo สร้างโฟลเดอร์ "%IMAGES_DIR%" ให้แล้ว
echo เอารูปที่จะตรวจ (.jpg หรือ .png) ไปวางในโฟลเดอร์ "%IMAGES_DIR%" แล้วรันไฟล์นี้อีกครั้ง
pause
exit /b 0

:run_detect
echo ตรวจสอบและติดตั้งไลบรารีที่ต้องใช้
python -c "import torch, torchvision, PIL" 2>nul
if errorlevel 1 python -m pip install torch torchvision pillow --quiet

echo พบรูปในโฟลเดอร์ "%IMAGES_DIR%" กำลังตรวจจับ
python infer_detector.py --model "%MODEL%" --images-dir "%IMAGES_DIR%" --output-dir "%RESULTS_DIR%"

echo.
echo เสร็จแล้ว ผลลัพธ์ (รูปที่วาดกรอบแล้ว) อยู่ในโฟลเดอร์ "%RESULTS_DIR%"
pause
