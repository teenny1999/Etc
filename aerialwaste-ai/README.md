# โปรเจกต์: ตรวจจับจุดลักลอบทิ้งกากของเสียด้วย Remote Sensing + AI

## เป้าหมาย
ทดลอง fine-tune โมเดล AI ให้ตรวจจับจุดลักลอบทิ้งกากของเสียจากภาพถ่ายทางอากาศ/ดาวเทียม
โดยเริ่มจากชุดข้อมูลสำเร็จรูป (AerialWaste) แทนการสร้างข้อมูล label เองจากศูนย์

โปรเจกต์นี้เป็นส่วนเสริมของ [ระบบติดตามตัวอย่างสิ่งแวดล้อม](../dashboard/) —
เมื่อโมเดลตรวจจับจุดต้องสงสัยได้ในอนาคต จะนำพิกัดไปโหลดเข้าชีท `Sites` เพื่อ
วางแผนเก็บตัวอย่างดิน/น้ำ/อากาศต่อได้

## ชุดข้อมูลที่ใช้: AerialWaste
- คำอธิบาย: ภาพถ่ายทางอากาศ/ดาวเทียม (airborne, WorldView-3, GoogleEarth) annotate โดยผู้เชี่ยวชาญ
  มีภาพบวก (มีจุดทิ้งขยะ) 3,478 ภาพ และภาพลบ 6,956 ภาพ พร้อม metadata (ประเภทขยะ, evidence, severity)
  และ segmentation mask แบบ COCO format
- แหล่งดาวน์โหลดภาพ **และ** metadata (training.json / testing.json): https://zenodo.org/record/7034381
  (ทั้งภาพและไฟล์ JSON อยู่บน Zenodo ทั้งคู่ — ตรวจสอบแล้วว่า repo บน GitHub **ไม่ได้มีไฟล์ข้อมูลจริงอยู่เลย**
  มีแค่ utility scripts/notebooks สำหรับใช้ร่วมกับข้อมูลที่ดาวน์โหลดมาจาก Zenodo)
- utility scripts + notebooks (DataLoader, Visualizer, Statistics ฯลฯ) สำหรับใช้กับข้อมูล: https://github.com/nahitorres/AerialWaste
- เว็บไซต์โปรเจกต์: https://aerialwaste.org/
- License: Creative Commons CC BY-NC-ND — ห้ามใช้เชิงพาณิชย์/ดัดแปลงแจกจ่ายต่อ
  (ใช้ภายในหน่วยงานราชการเพื่องาน non-commercial น่าจะเข้าข่าย แต่ควรอ่าน LICENSE เต็มก่อนเผยแพร่ผลงานต่อ)
- หมายเหตุ: ถ้าใช้ภาพจาก Google Earth ต้องปฏิบัติตามเงื่อนไขของ Google เพิ่มเติมด้วย

ยืนยันจาก README ของ https://github.com/nahitorres/AerialWaste แล้วว่า field ต่อภาพ
ที่โค้ดในโปรเจกต์นี้ใช้ (`file_name`, `is_candidate_location`) ถูกต้องตรงกับที่เจ้าของ
ชุดข้อมูลระบุไว้จริง (นอกจากนี้ยังมี `id`, `evidence`, `severity`, `width`, `height`,
`site_type`, `is_valid_fine_grain`, `categories` และ segmentation mask แบบ COCO
สำหรับขั้น segmentation ในอนาคต)

## โครงสร้างโฟลเดอร์ที่ต้องเตรียม
```
aerialwaste/
  ├── training.json
  ├── testing.json
  └── images/
      ├── xxx.jpg
      ├── yyy.jpg
      └── ...
```

## ไฟล์ในโฟลเดอร์นี้
| ไฟล์ | หน้าที่ |
|---|---|
| `train_aerialwaste_baseline.py` | fine-tune ResNet18 เป็น binary classifier (มี/ไม่มีจุดทิ้งขยะ) |
| `infer_aerialwaste.py` | โหลดโมเดลที่ train แล้ว มาทำนายภาพใหม่ (เช่น ภาพโดรนไทย) |
| `requirements.txt` | รายการไลบรารีที่ต้องติดตั้ง |
| `tests/make_synthetic_dataset.py` | สร้างข้อมูลปลอม (random noise) ไว้ smoke-test โค้ดโดยไม่ต้องมีข้อมูลจริง |

## สถานะปัจจุบัน (อัปเดตล่าสุด)
- ✅ ติดตั้งไลบรารี (`torch` 2.14 / `torchvision` 0.29 / `pillow` / `scikit-learn`) และรันได้จริงแล้ว (CPU only ในสภาพแวดล้อมนี้)
- ✅ รัน smoke test เต็มรูปแบบด้วยข้อมูลปลอม (`tests/make_synthetic_dataset.py` → `train_aerialwaste_baseline.py` → `infer_aerialwaste.py`)
  ผ่านทั้ง pipeline ไม่มี error ทาง syntax/logic (loss ลดลง, บันทึกโมเดล, inference คืนผลลัพธ์เรียงตามความมั่นใจได้ถูกต้อง)
- ❌ **ยังดาวน์โหลดข้อมูลจริงจาก Zenodo ไม่ได้** — สภาพแวดล้อมนี้เข้าถึง `zenodo.org` ไม่ได้เลย (connection timeout
  ทั้งจาก `curl` และจาก web-fetch tool คนละตัว) ส่วน `github.com`/`raw.githubusercontent.com` เข้าถึงได้ปกติ
  แต่ตรวจสอบแล้วว่า repo https://github.com/nahitorres/AerialWaste **ไม่มีไฟล์ข้อมูลจริง** (ทั้งภาพและ
  training.json/testing.json) อยู่เลย มีแค่ utility scripts/notebooks — ข้อมูลจริงทั้งหมดต้องไปเอาจาก Zenodo
  บนเครื่อง/บริการที่เข้าถึงได้ (เช่นเครื่องส่วนตัว หรือ Google Colab)
- ยังไม่เคยรันกับข้อมูลจริง — ตัวเลข accuracy/loss ที่เห็นตอน smoke test เป็นข้อมูลสุ่ม ไม่มีความหมายเชิงโมเดล

## สิ่งที่ต้องทำต่อ (บนเครื่องที่มีเน็ตเข้าถึง Zenodo ได้)
1. ดาวน์โหลดข้อมูลทั้งหมด (ภาพ + `training.json` + `testing.json`) จาก Zenodo
   (https://zenodo.org/record/7034381) โดยตรง — ไม่มีทางลัดผ่าน GitHub เพราะ repo
   บน GitHub ไม่มีไฟล์ข้อมูลจริง จัดเป็นโครงสร้างโฟลเดอร์ตามที่ระบุด้านบน
2. ติดตั้งไลบรารี: `pip install -r requirements.txt --break-system-packages`
3. รัน: `python train_aerialwaste_baseline.py --data-dir /path/to/aerialwaste`
   - ถ้า error เรื่อง key ใน JSON ไม่ตรง สคริปต์จะบอก key ที่เจอจริงในข้อความ error ให้แก้ตามนั้น
4. ถ้า train ผ่านแล้วผลออกมาไม่ดี ลองปรับ `--epochs` หรือ `--lr` (ดู `python train_aerialwaste_baseline.py --help`)
5. ทดสอบโมเดลกับภาพโดรน/ดาวเทียมของพื้นที่จริงในไทย:
   `python infer_aerialwaste.py --model aerialwaste_resnet18_baseline.pt --images-dir /path/to/thai_images`
   ดูว่าแม่นแค่ไหน ถ้าไม่พอให้เก็บภาพไทยจริงมา fine-tune เพิ่ม
6. ขั้นที่สูงกว่านั้น: ขยับจาก classification ไปเป็น segmentation/object detection
   (ใช้ mask ที่มีอยู่ใน AerialWaste เป็น COCO format — ใช้กับ Detectron2/MMDetection ได้)

## บริบทของงาน (อ้างอิง)
- ทำในนามการเตรียมข้อมูล/ต้นแบบสำหรับหัวข้อ "การป้องกันการลักลอบทิ้งกากของเสีย
  ด้วยการใช้ภาพถ่ายทางอากาศ Remote Sensing กับ AI Learning"
- แผนระยะสั้น: ทำแบบเล็กๆ เอง (ไม่รอ MOU/งบใหญ่) โดยมีความสามารถบินโดรนเองได้
- แนวทางระยะยาว: ใช้ AerialWaste เป็น baseline ก่อน แล้ว fine-tune ด้วยภาพไทยที่สะสมจากงานภาคสนามจริง
