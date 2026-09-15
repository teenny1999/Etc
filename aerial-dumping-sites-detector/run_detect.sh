#!/usr/bin/env bash
# run_detect.sh — ตรวจจับจุดทิ้งขยะในภาพ ไม่ต้องพิมพ์ path ใดๆ
#
# วิธีใช้ครั้งแรก:
#   1. วางไฟล์นี้ + infer_detector.py + dumping_sites_fasterrcnn.pt ไว้โฟลเดอร์เดียวกัน
#   2. รัน: bash run_detect.sh  (จะสร้างโฟลเดอร์ "images" ให้อัตโนมัติ)
#   3. เอารูปที่จะตรวจไปวางในโฟลเดอร์ "images" ที่สร้างขึ้น
#   4. รัน: bash run_detect.sh อีกครั้ง
#   5. ผลลัพธ์ (รูปที่วาดกรอบแล้ว) จะอยู่ในโฟลเดอร์ "results"

set -euo pipefail
cd "$(dirname "$0")"

MODEL="dumping_sites_fasterrcnn.pt"
IMAGES_DIR="images"
RESULTS_DIR="results"

if [ ! -f "$MODEL" ]; then
  echo "ไม่พบไฟล์โมเดล $MODEL ในโฟลเดอร์นี้"
  echo "ตรวจสอบว่าเอา dumping_sites_fasterrcnn.pt มาวางไว้โฟลเดอร์เดียวกับสคริปต์นี้แล้ว"
  exit 1
fi

if [ ! -f "infer_detector.py" ]; then
  echo "ไม่พบไฟล์ infer_detector.py ในโฟลเดอร์นี้"
  exit 1
fi

mkdir -p "$IMAGES_DIR"

# เช็คว่ามีรูปในโฟลเดอร์ images ไหม
shopt -s nullglob
IMAGE_FILES=("$IMAGES_DIR"/*.jpg "$IMAGES_DIR"/*.jpeg "$IMAGES_DIR"/*.png "$IMAGES_DIR"/*.JPG "$IMAGES_DIR"/*.PNG)
shopt -u nullglob

if [ ${#IMAGE_FILES[@]} -eq 0 ]; then
  echo "สร้างโฟลเดอร์ '$IMAGES_DIR' ให้แล้ว"
  echo "เอารูปที่จะตรวจ (.jpg/.png) ไปวางในโฟลเดอร์ '$IMAGES_DIR' แล้วรันสคริปต์นี้อีกครั้ง"
  exit 0
fi

echo "ตรวจสอบ/ติดตั้งไลบรารีที่ต้องใช้..."
PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
"$PY" -c "import torch, torchvision, PIL" 2>/dev/null || "$PY" -m pip install torch torchvision pillow --quiet

echo "พบรูป ${#IMAGE_FILES[@]} ไฟล์ในโฟลเดอร์ '$IMAGES_DIR' — กำลังตรวจจับ..."
"$PY" infer_detector.py --model "$MODEL" --images-dir "$IMAGES_DIR" --output-dir "$RESULTS_DIR"

echo ""
echo "เสร็จแล้ว! ผลลัพธ์ (รูปที่วาดกรอบแล้ว) อยู่ในโฟลเดอร์ '$RESULTS_DIR'"
