#!/usr/bin/env bash
# quickstart.sh — เตรียมทุกอย่างแล้วเริ่มเทรนโมเดลตรวจจับจุดทิ้งขยะทันที
#
# ใช้งาน:
#   1. ดาวน์โหลด dataset (format: COCO, "download zip to computer") จาก
#      https://universe.roboflow.com/object-detection-of-illegal-dumping-sites/aerial-dumping-sites
#   2. รัน:  bash quickstart.sh /path/to/aerial-dumping-sites.zip
#      (หรือถ้าแตกไฟล์ไว้แล้ว: bash quickstart.sh /path/to/aerial-dumping-sites/  )
#
# สคริปต์นี้จะ: ติดตั้งไลบรารี -> แตกไฟล์ zip (ถ้าจำเป็น) -> เช็ค GPU -> เริ่มเทรน
# log ทั้งหมดจะถูกบันทึกไว้ที่ train.log ในโฟลเดอร์นี้ด้วย

set -euo pipefail
cd "$(dirname "$0")"

if [ $# -lt 1 ]; then
  echo "วิธีใช้: bash quickstart.sh <path ไปยัง .zip ที่ดาวน์โหลดมา หรือโฟลเดอร์ที่แตกไว้แล้ว>"
  echo "ดาวน์โหลด dataset (เลือก format: COCO) จาก:"
  echo "  https://universe.roboflow.com/object-detection-of-illegal-dumping-sites/aerial-dumping-sites"
  exit 1
fi

INPUT_PATH="$1"
DATA_DIR="./aerial-dumping-sites"

echo "=== [1/4] ติดตั้งไลบรารี ==="
PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
"$PY" -m pip install -r requirements.txt --quiet

echo ""
echo "=== [2/4] เตรียมข้อมูล ==="
if [ -f "$INPUT_PATH" ]; then
  echo "พบไฟล์ zip: $INPUT_PATH — กำลังแตกไฟล์ไปที่ $DATA_DIR ..."
  rm -rf "$DATA_DIR"
  mkdir -p "$DATA_DIR"
  "$PY" -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$INPUT_PATH" "$DATA_DIR"
elif [ -d "$INPUT_PATH" ]; then
  echo "ใช้โฟลเดอร์ข้อมูลที่มีอยู่แล้ว: $INPUT_PATH"
  DATA_DIR="$INPUT_PATH"
else
  echo "ไม่พบไฟล์/โฟลเดอร์: $INPUT_PATH"
  exit 1
fi

if [ ! -f "$DATA_DIR/train/_annotations.coco.json" ]; then
  echo "โครงสร้างข้อมูลไม่ตรงที่คาดไว้ — หา $DATA_DIR/train/_annotations.coco.json ไม่เจอ"
  echo "ตรวจสอบว่าโหลด export format 'COCO' มา และแตกไฟล์ถูกที่"
  exit 1
fi
echo "ข้อมูลพร้อมใช้งานที่: $DATA_DIR"

echo ""
echo "=== [3/4] เช็คสถานะ GPU ==="
"$PY" -c "
import torch
if torch.cuda.is_available():
    print(f'พบ GPU: {torch.cuda.get_device_name(0)} — จะใช้ CUDA เทรน (เร็ว)')
else:
    print('ไม่พบ GPU — จะเทรนบน CPU (ช้ากว่ามาก ลองลด --epochs ถ้ารอไม่ไหว)')
"

echo ""
echo "=== [4/4] เริ่มเทรน (log อยู่ที่ train.log ด้วย) ==="
"$PY" train_detector.py --data-dir "$DATA_DIR" --epochs 5 2>&1 | tee train.log

echo ""
echo "เสร็จแล้ว! โมเดลถูกบันทึกไว้ที่ dumping_sites_fasterrcnn.pt"
