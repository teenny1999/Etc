# Aerial-Dumping-Sites Detector

Object detection baseline สำหรับหาตำแหน่ง (bounding box) ของจุดทิ้งขยะผิดกฎหมาย
ในภาพถ่ายทางอากาศ — เป็นส่วนเสริมของ [`../aerialwaste-ai/`](../aerialwaste-ai/)
ที่เป็น binary classification (มี/ไม่มี) เท่านั้น โปรเจกต์นี้บอกตำแหน่งในภาพได้ด้วย

## ชุดข้อมูล: Aerial-Dumping-Sites (Roboflow Universe)
- แหล่งข้อมูล: https://universe.roboflow.com/object-detection-of-illegal-dumping-sites/aerial-dumping-sites
- License: CC BY 4.0
- 1,555 ภาพ, class เดียว: `dumping-sites` (object detection + segmentation polygon)
- Export format ที่ใช้: **COCO JSON**
- ตรวจสอบโครงสร้างจริงแล้ว (ดาวน์โหลดและแตกไฟล์ทดสอบแล้ว):
  - `train/`: 1,492 ภาพ, 11,258 annotations
  - `valid/`: 63 ภาพ
  - ไม่มี `test/` split
  - แต่ละ split มีไฟล์ `_annotations.coco.json` (มาตรฐาน COCO: `images`, `annotations`, `categories`)
  - `categories` มี 2 entry: `id=0` (`"none"`, placeholder ที่ Roboflow ใส่มาให้อัตโนมัติ ไม่ได้ใช้จริง)
    และ `id=1` (`"dumping-sites"`, ตัวจริงที่ annotation ทั้งหมดอ้างถึง)

## วิธีใช้ (ทางลัด — เร็วสุด)
1. ดาวน์โหลด dataset (format: **COCO**, เลือก "download zip to computer") จากลิงก์ด้านบน
   — **ไม่ต้องแตกไฟล์เอง**
2. รันคำสั่งเดียว:
   ```
   bash quickstart.sh /path/to/aerial-dumping-sites.zip
   ```
   สคริปต์จะจัดการให้ครบ: ติดตั้งไลบรารี → แตกไฟล์ zip ให้ถูกโครงสร้าง → เช็คว่ามี GPU
   ไหม → เริ่มเทรนทันที (log บันทึกไว้ที่ `train.log` ด้วย)
3. ได้โมเดล `dumping_sites_fasterrcnn.pt` เมื่อเทรนเสร็จ

## วิธีใช้ (แบบละเอียด/ปรับเองทีละขั้น)
1. ดาวน์โหลด dataset ตามข้อ 1 ด้านบน แล้วแตกไฟล์ zip ให้ได้โครงสร้าง:
   ```
   aerial-dumping-sites/
     ├── train/
     │   ├── _annotations.coco.json
     │   └── *.jpg
     └── valid/
         ├── _annotations.coco.json
         └── *.jpg
   ```
2. ติดตั้งไลบรารี: `pip install -r requirements.txt --break-system-packages`
3. รัน: `python train_detector.py --data-dir /path/to/aerial-dumping-sites --epochs 5`
   (ปรับ `--epochs`, `--lr`, `--batch-size` ได้ตามต้องการ ดู `--help`)

## สถานะปัจจุบัน
- ✅ ดาวน์โหลดข้อมูลจริงมาทดสอบแล้ว (ผู้ใช้อัปโหลดผ่าน Google Drive) ตรวจสอบโครงสร้าง COCO
  ตรงตามที่คาดไว้ทุกจุด (field names, category id, จำนวนภาพ/annotation)
- ✅ รัน `train_detector.py` กับข้อมูลจริงแล้ว (smoke test: 4 ภาพ, 1 epoch, CPU) —
  pipeline ทำงานถูกต้องครบ (โหลดข้อมูล → forward/backward → บันทึกโมเดล → evaluate)
  ไม่มี error ทาง syntax/logic
- ✅ ทดสอบ `quickstart.sh` แบบ end-to-end แล้วด้วยข้อมูลย่อย (4 train + 2 valid ภาพ,
  5 epochs เต็ม) — ติดตั้ง/แตกไฟล์/เช็ค GPU/เทรน/บันทึกโมเดล ทำงานถูกต้องหมด
  (loss ลดลงต่อเนื่องจริง 1.03 → 0.63 ตลอด 5 epochs ยืนยันว่าโมเดล "เรียนรู้" ได้จริง)
- **จับเวลาจริงบนเครื่องนี้ (CPU, ไม่มี GPU): ~5.78 วินาที/ภาพ** → เทรนเต็ม 1,492 ภาพ
  5 epochs ใช้เวลาประมาณ **12 ชั่วโมง** — ถ้ามี GPU (แม้แค่การ์ดจอโน้ตบุ๊กทั่วไป) จะเร็วกว่านี้มาก
  แนะนำให้รันบนเครื่องที่มี GPU หรือ Google Colab แทนการรันบน CPU ล้วน

## หมายเหตุเรื่องการประเมินผล
`evaluate_simple()` ในสคริปต์เป็นการเช็ค sanity แบบง่าย (เทียบจำนวนกล่องที่ทำนายกับจำนวนกล่องจริง)
**ไม่ใช่ COCO mAP มาตรฐาน** — ถ้าต้องการ mAP ที่ใช้เทียบกับงานวิจัยอื่นได้ ให้ติดตั้ง `pycocotools`
แล้วใช้ `COCOeval` กับผลลัพธ์ที่ได้จาก `model(images)` ในโหมด eval

## ขั้นถัดไป
1. รันบน GPU/Colab จริงด้วยข้อมูลทั้งหมด (`--limit` ไม่ต้องใส่) ปรับ `--epochs`/`--lr` ตามผลที่ได้
2. ถ้าต้องการความแม่นยำระดับ pixel (ไม่ใช่แค่กรอบสี่เหลี่ยม) ข้อมูลมี segmentation polygon
   อยู่แล้วใน `_annotations.coco.json` (`annotations[i]["segmentation"]`) — เปลี่ยนมาใช้
   Mask R-CNN (`torchvision.models.detection.maskrcnn_resnet50_fpn_v2`) แทนได้โดยแก้ dataset
   loader ให้คืนค่า `masks` เพิ่มจาก polygon เหล่านี้
3. ทดสอบ (inference) กับภาพโดรน/ดาวเทียมของพื้นที่จริงในไทย เหมือนแผนของ `aerialwaste-ai/`
4. เทียบผลกับโมเดล classification ใน `aerialwaste-ai/` ว่าแบบไหนเหมาะกับงานหน้างานมากกว่า
