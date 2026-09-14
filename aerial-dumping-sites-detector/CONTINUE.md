# ทำต่อ: เทรนโมเดลตรวจจับจุดทิ้งขยะ (Aerial-Dumping-Sites)

ไฟล์นี้เขียนไว้ให้ Claude Code (ที่รันบนคอมของผู้ใช้ ไม่ใช่ sandbox บนคลาวด์)
อ่านแล้วทำงานต่อได้เลยโดยไม่ต้องถามบริบทเพิ่ม

## สรุปโปรเจกต์ (บริบท)
เป้าหมาย: ตรวจจับจุดลักลอบทิ้งกากของเสียจากภาพถ่ายทางอากาศ/ดาวเทียม ด้วย AI
เพื่อใช้ประกอบงาน "การป้องกันการลักลอบทิ้งกากของเสียด้วยการใช้ภาพถ่ายทางอากาศ
Remote Sensing กับ AI Learning" เป็นส่วนเสริมของ repo นี้ที่มีระบบ dashboard
ติดตามตัวอย่างสิ่งแวดล้อม (`../dashboard/`) อยู่แล้ว

ใน repo มี 2 โปรเจกต์ย่อยด้าน AI:
- `aerialwaste-ai/` — binary classification (มี/ไม่มีจุดทิ้งขยะ) ใช้ dataset AerialWaste
  จาก Zenodo — **ยังติดปัญหาดาวน์โหลดข้อมูลไม่ได้** เพราะ sandbox ที่เขียนโค้ดนี้เข้าถึง
  zenodo.org ไม่ได้เลย (ยืนยันแล้วว่าเป็นปัญหาการเชื่อมต่อกับเซิร์ฟเวอร์ CERN โดยเฉพาะ
  ไม่ใช่ปัญหาเน็ตทั่วไป) — ถ้าคอมนี้เข้า zenodo.org ได้ปกติ ให้ลองทำอันนี้ต่อได้เหมือนกัน
- `aerial-dumping-sites-detector/` (**โฟลเดอร์นี้**) — object detection (บอกตำแหน่ง
  bounding box) ใช้ dataset "Aerial-Dumping-Sites" จาก Roboflow Universe แทน
  เพราะดาวน์โหลด/ทดสอบโค้ดกับข้อมูลจริงสำเร็จแล้ว **นี่คืองานหลักที่ต้องทำต่อ**

## สถานะปัจจุบันของ `aerial-dumping-sites-detector/`
- เขียน `train_detector.py` (fine-tune Faster R-CNN ResNet50-FPN v2 pretrained
  ให้ตรวจจับ class เดียว "dumping-sites") เสร็จแล้ว
- ทดสอบกับข้อมูลจริงที่ดาวน์โหลดมาแล้ว (ผ่าน Google Drive) ยืนยันว่าโครงสร้าง COCO
  ตรงตามที่คาดไว้ (`train/` 1,492 ภาพ/11,258 annotations, `valid/` 63 ภาพ,
  ไม่มี `test/`, category จริงคือ `dumping-sites` id=1)
- `quickstart.sh` ทดสอบ end-to-end แล้วด้วยข้อมูลย่อย (4+2 ภาพ, 5 epochs เต็ม)
  ทำงานถูกต้องทุกจุด loss ลดลงจริง (1.03 → 0.63) — สคริปต์นี้ใช้งานได้จริง
- **ยังไม่เคย train เต็มรูปแบบด้วยข้อมูลทั้งหมด** — บน sandbox คลาวด์ (ไม่มี GPU)
  จับเวลาจริงได้ ~5.78 วินาที/ภาพ → เทรนเต็ม 1,492 ภาพ 5 epochs ใช้เวลา ~12 ชั่วโมง
  ถ้าคอมนี้มี GPU จะเร็วกว่ามาก

## ต้องทำอะไรต่อ (ทำตามลำดับ)

1. **เช็คว่ามี GPU ให้ใช้ไหม** (ถ้ามี NVIDIA GPU จะเร็วกว่า CPU มาก):
   ```
   python3 -c "import torch; print(torch.cuda.is_available())"
   ```
   ถ้ายังไม่ได้ติดตั้ง torch หรือได้ `False` ทั้งที่มีการ์ดจอ NVIDIA จริง ให้ไปที่
   https://pytorch.org/get-started/locally/ เลือกคำสั่งติดตั้งที่ตรงกับ CUDA driver
   ของเครื่องนี้ก่อน (แทนที่จะใช้ `requirements.txt` เฉยๆ ซึ่งอาจได้ CPU-only build)

2. **ดาวน์โหลด dataset จาก Roboflow:**
   https://universe.roboflow.com/object-detection-of-illegal-dumping-sites/aerial-dumping-sites
   → แท็บ **Dataset** → เลือก version → **Download Dataset** → format **COCO**
   → **"download zip to computer"** (ไม่ต้องแตกไฟล์เอง)

3. **รันคำสั่งเดียว** (อยู่ในโฟลเดอร์ `aerial-dumping-sites-detector/`):
   ```
   bash quickstart.sh /path/ไปยัง/aerial-dumping-sites.zip
   ```
   สคริปต์จัดการให้ครบ: ติดตั้งไลบรารี (`pip install -r requirements.txt`) →
   แตกไฟล์ zip ให้ถูกโครงสร้าง → เช็ค GPU → เริ่มเทรน 5 epochs (ปรับ epoch ได้โดยแก้
   บรรทัดสุดท้ายใน `quickstart.sh` หรือรัน `train_detector.py` ตรงๆ พร้อม `--epochs`)
   log จะถูกบันทึกไว้ที่ `train.log` ด้วย

4. **ถ้า train ผ่านแล้วผลไม่ดี:**
   - ลองเพิ่ม `--epochs` (ค่าเริ่มต้น 5 อาจน้อยไปสำหรับข้อมูลจริง 1,492 ภาพ)
   - ลองปรับ `--lr` (ค่าเริ่มต้น 1e-4)
   - เช็คผลด้วย `evaluate_simple()` ในสคริปต์ — เป็นแค่การเช็ค sanity เบื้องต้น
     (เทียบจำนวนกล่องที่ทำนายกับของจริง) **ไม่ใช่ COCO mAP มาตรฐาน** ถ้าต้องการ mAP
     จริงให้ติดตั้ง `pycocotools` แล้วเขียน `COCOeval` เพิ่มเอง

5. **ขั้นถัดไปหลังโมเดลใช้ได้ดีแล้ว:**
   - ทดสอบ (inference) กับภาพโดรน/ดาวเทียมของพื้นที่จริงในไทย ดูว่าแม่นแค่ไหน
     (ยังไม่มีสคริปต์ inference สำหรับโมเดล detection นี้โดยเฉพาะ — ต่างจาก
     `aerialwaste-ai/infer_aerialwaste.py` ที่มีแล้วแต่ใช้กับโมเดล classification
     คนละตัว ถ้าต้องการ ให้เขียนสคริปต์ใหม่ที่โหลด `dumping_sites_fasterrcnn.pt`
     แล้ววาด bounding box ที่ทำนายได้ลงบนภาพ)
   - ถ้าอยากได้ความแม่นยำระดับ pixel (ไม่ใช่แค่กรอบสี่เหลี่ยม): ข้อมูลมี segmentation
     polygon อยู่แล้วใน `_annotations.coco.json` (`annotations[i]["segmentation"]`)
     — เปลี่ยนไปใช้ `torchvision.models.detection.maskrcnn_resnet50_fpn_v2` แทนได้
     โดยแก้ dataset loader ให้คืนค่า `masks` เพิ่มจาก polygon เหล่านี้ (แปลง polygon
     เป็น binary mask ด้วย `pycocotools.mask` หรือ `PIL.ImageDraw.polygon`)
   - เทียบกับโมเดล classification ใน `aerialwaste-ai/` (ถ้าทำสำเร็จ) ว่าแบบไหนเหมาะ
     กับงานหน้างานมากกว่า

## หมายเหตุสำคัญ
- ถ้าเจอ error ตอนติดตั้ง torch/torchvision ให้ลองเพิ่ม `--break-system-packages`
  ต่อท้ายคำสั่ง pip (จำเป็นบน Debian/Ubuntu บางเวอร์ชันที่ป้องกัน pip เขียนทับ
  system packages)
- ไฟล์โมเดล (`*.pt`) และโฟลเดอร์ข้อมูล (`aerial-dumping-sites/`) ถูกใส่ใน
  `.gitignore` ไว้แล้ว ไม่ต้อง commit เข้า git (ไฟล์ใหญ่เกินไป)
- Repo/branch: `teenny1999/Etc` branch `claude/vibrant-heisenberg-puc5a1`
