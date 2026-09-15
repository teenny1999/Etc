# ทำต่อบนคอมนี้ (Claude Code local)

ไฟล์นี้เขียนไว้ให้ Claude Code ที่รันบนคอมของผู้ใช้ (มี GPU, เข้าอินเทอร์เน็ตได้ปกติ
ไม่ผ่าน proxy แบบ sandbox คลาวด์ที่เขียนโค้ดนี้) อ่านแล้วทำงานต่อได้เลยโดยไม่ต้องถาม
บริบทเพิ่ม — งานมี 2 โปรเจกต์ย่อยด้าน AI ในนี้ ให้ทำต่อทั้งคู่

## บริบทรวม
เป้าหมาย: ตรวจจับจุดลักลอบทิ้งกากของเสียจากภาพถ่ายทางอากาศ/ดาวเทียม ด้วย AI
เพื่อใช้ประกอบงาน "การป้องกันการลักลอบทิ้งกากของเสียด้วยการใช้ภาพถ่ายทางอากาศ
Remote Sensing กับ AI Learning" — เป็นส่วนเสริมของ dashboard ติดตามตัวอย่าง
สิ่งแวดล้อมที่มีอยู่แล้วใน repo นี้ (`dashboard/`, `sheets-template/`)

ทำไมต้องย้ายมาทำบนคอมนี้: sandbox คลาวด์ที่เขียนโค้ดทั้งหมดนี้เข้า zenodo.org
ไม่ได้เลย (connection timeout ยืนยันแล้วว่าไม่ใช่แค่ curl แต่เป็นปัญหาการเชื่อมต่อ
กับเซิร์ฟเวอร์ CERN จริงๆ) และ universe.roboflow.com ก็โดน Cloudflare bot-challenge
บล็อกเครื่องมือ headless — ทั้งสองปัญหาไม่น่าเกิดกับคอมนี้เพราะเป็นเบราว์เซอร์ปกติ
ไม่ผ่าน proxy เดียวกัน

---

## โปรเจกต์ 1: `aerial-dumping-sites-detector/` — ทำไปไกลแล้ว ใกล้เสร็จ

### สถานะ
- โมเดล Faster R-CNN (ResNet50-FPN v2) เทรนไปแล้ว **5 epochs เต็ม** บน sandbox คลาวด์
  (CPU ล้วน ใช้เวลา ~9.5 ชั่วโมง) ด้วยข้อมูลจริงทั้งหมดจาก Roboflow
  (Aerial-Dumping-Sites: 1,492 train / 63 valid ภาพ)
- Loss ลดลงต่อเนื่องตลอด: 0.71 → 0.63 → 0.57 → 0.52 → **0.47** (ยังไม่ plateau —
  แปลว่าเทรนเพิ่มน่าจะช่วยได้อีก)
- ผลประเมินแบบง่ายบนชุด valid: 62/63 ภาพเจอจุดทิ้งขยะอย่างน้อย 1 จุด
  (629 กล่องจริง vs 911 กล่องที่ทาย — ทายเกินจริงพอสมควร ต้องดูภาพประกอบ)
- ผู้ใช้ทดสอบ `infer_detector.py` กับภาพจริงแล้ว **ใช้งานได้ แต่บอกว่ายังไม่แม่นพอ**
- ไฟล์โมเดล `dumping_sites_fasterrcnn.pt` (173MB) **ผู้ใช้มีอยู่แล้วในเครื่องนี้**
  (ส่งให้ผ่าน chat เป็นไฟล์แบ่งส่วน 7 ชิ้น + สคริปต์ `combine.sh`/`combine.bat`
  รวมกลับเป็นไฟล์เดียวแล้ว) — หาไฟล์นี้ในเครื่องก่อน ไม่ต้องเทรนใหม่ตั้งแต่ต้น
- ผู้ใช้มี GPU ใช้งานได้จริง (ยืนยันจาก log ที่ขึ้น `ใช้งานบน: cuda`)

### ต้องทำต่อ (เรียงตามลำดับ)
1. **หาไฟล์ `dumping_sites_fasterrcnn.pt` ที่ผู้ใช้มีอยู่แล้วในเครื่อง** (ถามผู้ใช้ว่า
   อยู่โฟลเดอร์ไหนถ้าไม่เจอ) — เอามาวางในโฟลเดอร์ `aerial-dumping-sites-detector/`
   ของ repo ที่ clone มา
2. **ดาวน์โหลดชุดข้อมูล Aerial-Dumping-Sites จาก Roboflow เอง** (คอมนี้เข้าได้ปกติ):
   https://universe.roboflow.com/object-detection-of-illegal-dumping-sites/aerial-dumping-sites
   → แท็บ Dataset → เลือก version → Download → format **COCO** →
   "download zip to computer" → แตกไฟล์ให้ได้ `train/` + `valid/` (มี
   `_annotations.coco.json` ในแต่ละโฟลเดอร์)
3. **เทรนต่อจากโมเดลเดิม** (ไม่ใช่เริ่มใหม่ — ใช้ `--resume`):
   ```
   pip install -r aerial-dumping-sites-detector/requirements.txt
   python aerial-dumping-sites-detector/train_detector.py \
     --data-dir path/to/aerial-dumping-sites \
     --resume path/to/dumping_sites_fasterrcnn.pt \
     --epochs 20
   ```
   ปรับ `--epochs` ตามที่เห็นสมควร (มี GPU ควรเร็วกว่า sandbox มาก ลองเพิ่มได้)
   สคริปต์เซฟ checkpoint ทุก epoch ไว้ที่ `dumping_sites_fasterrcnn_checkpoint.pt`
   กันไฟดับ/ปิดเครื่องกลางคัน (ดู `train_detector.py` — มี `--resume` built-in แล้ว)
4. **ทดสอบผลใหม่** ด้วย `infer_detector.py`:
   ```
   python aerial-dumping-sites-detector/infer_detector.py \
     --model dumping_sites_fasterrcnn.pt --images-dir <โฟลเดอร์ภาพทดสอบ> \
     --output-dir results
   ```
   ถ้ากล่องที่ทายเยอะเกินจริง (over-predict) ลองปรับ `--score-threshold` ให้สูงขึ้น
   (เช่น 0.7-0.8) ก่อนจะสรุปว่าโมเดลแย่ — อาจแค่ threshold default (0.5) ต่ำไป
5. ถ้ายังไม่แม่นพอหลังเทรนเพิ่ม: พิจารณาเก็บภาพไทยจริงมาผสม fine-tune เพิ่ม
   หรือขยับไปใช้ Mask R-CNN (ข้อมูลมี segmentation polygon อยู่แล้วใน
   `_annotations.coco.json`, ดู `annotations[i]["segmentation"]`)

---

## โปรเจกต์ 2: `aerialwaste-ai/` — ยังไม่เคยรันกับข้อมูลจริงเลย

### สถานะ
- มีสคริปต์ `train_aerialwaste_baseline.py` (ResNet18 binary classifier: มี/ไม่มี
  จุดทิ้งขยะ) พร้อมใช้ — ทดสอบ pipeline ด้วยข้อมูลสังเคราะห์ (synthetic) แล้วว่า
  โค้ดรันได้ไม่มี bug แต่ **ยังไม่เคยรันกับข้อมูลจริงจาก AerialWaste dataset เลย**
  เพราะ sandbox คลาวด์เข้า zenodo.org ไม่ได้
- ยืนยันจาก README จริงของ https://github.com/nahitorres/AerialWaste แล้วว่า
  field ที่โค้ดใช้ (`file_name`, `is_candidate_location`) ถูกต้องตรงกับที่เจ้าของ
  ชุดข้อมูลระบุไว้จริง — ไม่น่ามีปัญหาเรื่อง field name ผิด
- **สำคัญ**: repo GitHub ของ AerialWaste (nahitorres/AerialWaste) มีแค่ utility
  scripts/notebooks เท่านั้น **ไม่มีตัวข้อมูลจริง** (ทั้งภาพและ training.json/
  testing.json อยู่บน Zenodo ทั้งหมด) — อย่าเสียเวลาหาในนั้น

### ต้องทำต่อ (เรียงตามลำดับ)
1. **ดาวน์โหลดข้อมูลจาก Zenodo โดยตรง** (คอมนี้ควรเข้าได้ปกติ ต่างจาก sandbox):
   https://zenodo.org/records/7034381
   ดาวน์โหลดไฟล์ภาพทั้งหมด + `training.json` + `testing.json`
   **License เป็น CC BY-NC-ND** — ห้ามใช้เชิงพาณิชย์/ดัดแปลงแจกจ่ายต่อ ควรอ่าน
   LICENSE เต็มก่อนเผยแพร่ผลงานต่อสาธารณะ (ใช้ภายในหน่วยงานราชการเพื่อ
   non-commercial น่าจะเข้าข่ายได้)
2. จัดโครงสร้างโฟลเดอร์ตามที่ระบุใน `aerialwaste-ai/README.md`:
   ```
   aerialwaste/
     ├── training.json
     ├── testing.json
     └── images/
   ```
3. ติดตั้งไลบรารี: `pip install -r aerialwaste-ai/requirements.txt`
4. รัน:
   ```
   python aerialwaste-ai/train_aerialwaste_baseline.py \
     --data-dir path/to/aerialwaste --epochs 5
   ```
   **ถ้า error เรื่อง key ใน JSON ไม่ตรง** — สคริปต์จะพิมพ์ key ที่เจอจริงในไฟล์
   ให้ดู เอาไปแก้ `AerialWasteDataset.__getitem__` ใน `train_aerialwaste_baseline.py`
   ให้ตรงกับโครงสร้างจริง (ยังไม่เคยเห็นไฟล์จริง เผื่อโครงสร้างต่างจากที่คาดไว้)
5. ทดสอบผลด้วย `aerialwaste-ai/infer_aerialwaste.py` กับภาพไทยจริง (ถ้ามี)
6. เทียบผลกับโมเดล detection ในโปรเจกต์ 1 ว่าแบบไหน (classification มี/ไม่มี
   vs detection ชี้ตำแหน่ง) เหมาะกับงานหน้างานมากกว่า — อาจจะใช้ทั้งคู่ร่วมกัน
   ก็ได้ (classification กรองภาพเบื้องต้นเร็วๆ ก่อน แล้ว detection ชี้ตำแหน่งเฉพาะ
   ภาพที่น่าสงสัย)

---

## หมายเหตุทั่วไป
- Repo/branch: `teenny1999/Etc` branch `claude/vibrant-heisenberg-puc5a1`
- ทั้งสองโปรเจกต์มี `.gitignore` กันไฟล์โมเดล (`*.pt`) และโฟลเดอร์ข้อมูลไม่ให้
  หลุดเข้า git (ไฟล์ใหญ่เกินไปสำหรับ git ธรรมดา ไม่มี Git LFS ตั้งไว้)
- ถ้าเจอ error ตอนติดตั้ง torch/torchvision บน Windows ลองไม่ต้องใส่
  `--break-system-packages` (flag นั้นมีไว้สำหรับ Linux/sandbox ที่ป้องกัน pip
  เขียนทับ system packages เท่านั้น)
- เช็ค GPU ก่อนเริ่มเทรนเสมอ: `python -c "import torch; print(torch.cuda.is_available())"`
  ควรได้ `True` — ถ้าไม่ใช่ ให้ติดตั้ง torch เวอร์ชันที่ตรงกับ CUDA driver จาก
  https://pytorch.org/get-started/locally/ แทนการใช้ `requirements.txt` เฉยๆ
