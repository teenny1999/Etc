#!/usr/bin/env python3
"""ใส่ข้อมูลตัวอย่าง (สมมติ) ลงฐานข้อมูล เพื่อทดลองใช้งาน

    python seed_demo.py                 # ใส่ลง data/demo.db
    python app.py --db data/demo.db     # แล้วเปิดดู

ค่าทั้งหมดเป็นข้อมูลสมมติ ไม่ใช่ผลตรวจจริง
"""
import os
import sys

import app

path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(app.HERE, "data", "demo.db")
if os.path.exists(path):
    sys.exit(f"มีไฟล์ {path} อยู่แล้ว — ลบทิ้งก่อนถ้าต้องการสร้างใหม่")
app.DB_PATH = path
app.init_db()
con = app.connect()
U = "ข้อมูลตัวอย่าง"

for media, p, mn, mx, unit, ref in [
    ("surface_water", "pH", 5, 9, "", "ค่าสมมติเพื่อทดสอบ"),
    ("surface_water", "DO", 4, None, "mg/L", "ค่าสมมติเพื่อทดสอบ"),
    ("surface_water", "BOD", None, 2, "mg/L", "ค่าสมมติเพื่อทดสอบ"),
    ("surface_water", "Pb", None, 0.05, "mg/L", "ค่าสมมติเพื่อทดสอบ"),
    ("groundwater", "As", None, 0.01, "mg/L", "ค่าสมมติเพื่อทดสอบ"),
    ("groundwater", "Mn", None, 0.5, "mg/L", "ค่าสมมติเพื่อทดสอบ"),
    ("soil", "Pb", None, 400, "mg/kg", "ค่าสมมติเพื่อทดสอบ"),
    ("soil", "Cd", None, 37, "mg/kg", "ค่าสมมติเพื่อทดสอบ"),
    ("sediment", "Pb", None, 400, "mg/kg", "ค่าสมมติเพื่อทดสอบ"),
    ("sediment", "Hg", None, 0.15, "mg/kg", "ค่าสมมติเพื่อทดสอบ"),
]:
    app.save_standard(con, U, None, {"media": media, "parameter": p, "min": mn, "max": mx, "unit": unit,
                                     "reference": ref})

P = "ลักลอบทิ้งกากอุตสาหกรรม ฉะเชิงเทรา (ตัวอย่าง)"
sites = [
    ("SW-01", "คลองท้ายพื้นที่ลักลอบทิ้ง", "จุดเก็บน้ำผิวดิน", 13.735, 101.385, "ฉะเชิงเทรา"),
    ("SW-02", "คลองเหนือน้ำ (จุดอ้างอิง)", "จุดเก็บน้ำผิวดิน", 13.812, 101.352, "ฉะเชิงเทรา"),
    ("GW-01", "บ่อบาดาลบ้านเรือนใกล้เคียง", "บ่อน้ำใต้ดิน", 13.701, 101.441, "ฉะเชิงเทรา"),
    ("SD-01", "ตะกอนท้องคลอง", "จุดเก็บตะกอน", 13.744, 101.402, "ฉะเชิงเทรา"),
    ("SS-01", "ดินผิวหน้าพื้นที่กองกาก", "จุดเก็บดิน", 13.722, 101.468, "ปราจีนบุรี"),
    ("SS-02", "ดินแปลงเกษตรข้างเคียง", "จุดเก็บดิน", 13.858, 101.505, "ปราจีนบุรี"),
]
ids = {}
for code, name, cat, lat, lng, prov in sites:
    ids[code] = app.create_site(con, U, {"code": code, "name": name, "category": cat, "project": P,
                                         "province": prov, "lat": lat, "lng": lng})
app.create_site(con, U, {
    "code": "AREA-1", "name": "ขอบเขตพื้นที่กองกาก", "category": "พื้นที่โครงการ", "project": P,
    "province": "ปราจีนบุรี", "lat": 13.7225, "lng": 101.4685,
    "geometry": {"type": "Polygon", "coordinates": [[[101.465, 13.720], [101.472, 13.7205], [101.4715, 13.725],
                                                     [101.4655, 13.7245], [101.465, 13.720]]]}})

S = [
    ("SW-01", "surface_water", "2026-05-27", [("pH", "6.1", ""), ("DO", "2.8", "mg/L"), ("BOD", "6.5", "mg/L"),
                                              ("Pb", "0.12", "mg/L")]),
    ("SW-01", "surface_water", "2026-08-15", [("pH", "6.8", ""), ("DO", "4.6", "mg/L"), ("BOD", "2.4", "mg/L"),
                                              ("Pb", "0.03", "mg/L")]),
    ("SW-02", "surface_water", "2026-05-27", [("pH", "7.2", ""), ("DO", "6.1", "mg/L"), ("BOD", "1.2", "mg/L"),
                                              ("Pb", "<0.005", "mg/L")]),
    ("GW-01", "groundwater", "2026-05-28", [("As", "0.018", "mg/L"), ("Mn", "0.31", "mg/L")]),
    ("SD-01", "sediment", "2026-05-27", [("Pb", "512", "mg/kg"), ("Hg", "0.09", "mg/kg")]),
    ("SS-01", "surface_soil", "2026-05-29", [("Pb", "830", "mg/kg"), ("Cd", "12", "mg/kg")]),
]
# ประวัติย้อนหลัง (ตรวจติดตามรายไตรมาส) เพื่อให้กราฟแนวโน้มมีข้อมูลเทียบ
HIST = {
    "SW-01": ("surface_water", {"pH": ("", [7.1, 6.9, 6.4, 6.2]), "DO": ("mg/L", [5.8, 5.1, 3.9, 3.2]),
                                "BOD": ("mg/L", [1.4, 1.9, 3.1, 4.8]), "Pb": ("mg/L", [0.008, 0.011, 0.034, 0.061])}),
    "SW-02": ("surface_water", {"pH": ("", [7.3, 7.2, 7.4, 7.1]), "DO": ("mg/L", [6.4, 6.0, 6.3, 5.9]),
                                "BOD": ("mg/L", [1.0, 1.3, 0.9, 1.4]), "Pb": ("mg/L", ["<0.005", "<0.005", 0.006, "<0.005"])}),
    "GW-01": ("groundwater", {"As": ("mg/L", [0.004, 0.006, 0.009, 0.013]), "Mn": ("mg/L", [0.22, 0.25, 0.27, 0.29])}),
}
for code, (media, params) in HIST.items():
    for i, date in enumerate(["2025-05-20", "2025-08-19", "2025-11-18", "2026-02-17"]):
        S.append((code, media, date, [(p, str(vals[i]), unit) for p, (unit, vals) in params.items()]))

for code, media, date, res in S:
    app.create_sample(con, U, {"site_id": ids[code], "media": media, "sample_date": date, "sampler": "ทีมภาคสนาม",
                               "lab": "ห้องปฏิบัติการ (ตัวอย่าง)", "sample_code": f"{code}-{date[5:7]}",
                               "depth": "0-15 cm" if media.endswith("soil") else None,
                               "results": [{"parameter": p, "value_text": v, "unit": u} for p, v, u in res]})
con.commit()
con.close()
print(f"สร้างข้อมูลตัวอย่างแล้ว: {path}\nเปิดดูด้วย: python app.py --db \"{path}\"")
