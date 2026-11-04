"""ทดสอบ API: python -m unittest test_app.py"""
import base64
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from urllib.parse import quote

os.environ["FIELDDB_QUIET"] = "1"
import app  # noqa: E402

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>ฉะเชิงเทรา</name>
<Folder><name>จุดเก็บน้ำผิวดิน</name>
  <Placemark><name>(จุด 1)</name><description><![CDATA[คลอง<br>ท้ายโรงงาน]]></description>
    <Point><coordinates>101.50,13.70,0</coordinates></Point></Placemark>
  <Placemark><name>ขอบเขตบ่อ</name>
    <Polygon><outerBoundaryIs><LinearRing><coordinates>
      101.0,13.0,0 101.1,13.0,0 101.1,13.1,0 101.0,13.0,0</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
</Folder></Document></kml>"""


def make_docx(blocks):
    """สร้างไฟล์ .docx ขนาดเล็กสำหรับทดสอบ: blocks = ["ข้อความ", [[cell, ...], ...], ...]
    cell เป็น str หรือ (text, {"span": n, "vmerge": "restart"|"cont"})"""
    from xml.sax.saxutils import escape
    def para(t):
        return f"<w:p><w:r><w:t xml:space=\"preserve\">{escape(t)}</w:t></w:r></w:p>"
    body = []
    for b in blocks:
        if isinstance(b, str):
            body.append(para(b))
            continue
        rows = []
        for row in b:
            cells = []
            for c in row:
                text, opt = (c, {}) if isinstance(c, str) else c
                pr = ""
                if opt.get("span"):
                    pr += f'<w:gridSpan w:val="{opt["span"]}"/>'
                if opt.get("vmerge") == "restart":
                    pr += '<w:vMerge w:val="restart"/>'
                elif opt.get("vmerge") == "cont":
                    pr += "<w:vMerge/>"
                cells.append(f"<w:tc><w:tcPr>{pr}</w:tcPr>{para(text) if text else '<w:p/>'}</w:tc>")
            rows.append("<w:tr>" + "".join(cells) + "</w:tr>")
        body.append("<w:tbl>" + "".join(rows) + "</w:tbl>")
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           + "".join(body) + "</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


V = lambda t, m: (t, {"vmerge": m})
PCD_DOC = [
    "ผลตรวจวิเคราะห์ตัวอย่างคุณภาพสิ่งแวดล้อม",
    "สถานที่/โครงการ/โรงงานบริษัท      ทดสอบจังหวัด",
    "สถานการณ์      พื้นที่ลักลอบทิ้ง",
    "เก็บตัวอย่างวันที่       21-23 กันยายน 2569",
    "ประเภทตัวอย่าง      น้ำผิวดิน",
    [["ลำดับ", "รหัสตัวอย่าง", "เวลา", "รายละเอียดจุดเก็บตัวอย่าง", "ลักษณะทางกายภาพ", "pH", "DO (mg/l)"],
     ["1", "W1", "15.02 น.", "คลองหน้าวัด ต.หนองบอน", "น้ำตาล", "7.46", "3.27"],
     ["2", "W2", "15.50 น.", "บ่อน้ำดิบ", "ใส", "8.63", "7.99"],
     [("มาตรฐานคุณภาพน้ำในแหล่งน้ำผิวดิน(1)", {"span": 5}), "5.0 – 9.0", "> 4"],
     [("มาตรฐานน้ำทิ้งจากโรงงาน(2)", {"span": 5}), "5.0 – 9.0", "-"]],
    "(1) ประกาศคณะกรรมการสิ่งแวดล้อมแห่งชาติ ฉบับที่ 8 (พ.ศ. 2537)",
    "(2) การเกษตร)",
    "(2) ประกาศกระทรวงอุตสาหกรรม เรื่อง น้ำทิ้งจากโรงงาน",
    [[V("ลำดับ", "restart"), V("รหัสตัวอย่าง", "restart"), V("เวลา", "restart"), ("Heavy metals (mg/l)", {"span": 2})],
     [V("", "cont"), V("", "cont"), V("", "cont"), "Pb", "Total Hg"],
     ["1", "W1", "15.02 น.", "0.12", "<0.0005"],
     ["2", "W2", "15.50 น.", "<0.01", "0.0007"],
     [("มาตรฐานคุณภาพน้ำในแหล่งน้ำผิวดิน(1)", {"span": 3}), "<0.05", "<0.002"]],
    "(1) ประกาศคณะกรรมการสิ่งแวดล้อมแห่งชาติ ฉบับที่ 8 (พ.ศ. 2537)",
    [[V("พารามิเตอร์", "restart"), ("จุดเก็บตัวอย่าง", {"span": 2}), V("มาตรฐานคุณภาพน้ำผิวดิน*", "restart")],
     [V("", "cont"), "W1", "W1 (Dup)", V("", "cont")],
     [("สารอินทรีย์ระเหยง่าย (ไมโครกรัมต่อลิตร)", {"span": 4})],
     ["Toluene", "14", "15", "-"], ["Benzene", "ND", "ND", "-"]],
    "ประเภทตัวอย่าง      ดิน",
    [[V("รหัสตัวอย่าง", "restart"), V("รายละเอียดจุดเก็บตัวอย่าง", "restart"), ("Heavy metals (mg/kg)", {"span": 1})],
     [V("", "cont"), V("", "cont"), "Pb"],
     [("อำเภอวัฒนานคร จังหวัดสระแก้ว", {"span": 3})],
     ["S1", "จุดที่ 1 ติดกองกาก", "792"],
     [("มาตรฐานคุณภาพดิน(1)", {"span": 2}), "35,040"]],
]


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        app.DB_PATH = os.path.join(cls.tmp.name, "t.db")
        cls.srv = app.make_server("127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def call(self, method, path, body=None, raw=None, headers=None, user="ทดสอบ"):
        h = {"X-User": quote(user), **(headers or {})}
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req) as r:
                b = r.read()
                return r.status, (json.loads(b) if r.headers.get_content_type() == "application/json" else b)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_site_sample_history_restore(self):
        st, r = self.call("POST", "/api/sites", {"code": "SW-01", "name": "คลอง", "lat": "13.7", "lng": "101.5"})
        self.assertEqual(st, 200)
        sid = r["id"]
        self.call("POST", "/api/standards", {"media": "surface_water", "parameter": "Pb", "max": 0.05, "unit": "mg/L"})
        st, r = self.call("POST", "/api/samples", {
            "site_id": sid, "media": "surface_water", "sample_date": "2026-05-27",
            "results": [{"parameter": "Pb", "value_text": "0.08", "unit": "mg/L"},
                        {"parameter": "pH", "value_text": "7.1"},
                        {"parameter": "Cd", "value_text": "<0.001"}]})
        self.assertEqual(st, 200)
        smp = r["id"]

        _, d = self.call("GET", f"/api/sites/{sid}")
        res = {x["parameter"]: x for x in d["samples"][0]["results"]}
        self.assertEqual(res["Pb"]["exceed"], 1)          # เกินมาตรฐาน
        self.assertIsNone(res["Cd"]["value"])               # <DL ไม่นับเป็นตัวเลข
        _, sites = self.call("GET", "/api/sites")
        self.assertEqual(next(s for s in sites if s["id"] == sid)["n_exceed"], 1)

        # แก้ค่า แล้วตรวจว่ามีประวัติ + ย้อนกลับได้
        self.call("PUT", f"/api/samples/{smp}", {"results": [{"parameter": "Pb", "value_text": "0.01"}]},
                  user="สมหญิง")
        _, hist = self.call("GET", f"/api/history?entity=sample&entity_id={smp}")
        self.assertEqual([h["action"] for h in hist], ["update", "create"])
        self.assertEqual(hist[0]["user"], "สมหญิง")
        self.assertEqual(len(hist[0]["before"]["results"]), 3)
        self.call("POST", f"/api/history/{hist[0]['id']}/restore")
        _, d = self.call("GET", f"/api/sites/{sid}")
        self.assertEqual(len(d["samples"][0]["results"]), 3)

        # ลบจุด แล้วกู้คืน
        self.call("DELETE", f"/api/sites/{sid}")
        _, sites = self.call("GET", "/api/sites")
        self.assertNotIn(sid, [s["id"] for s in sites])
        _, hist = self.call("GET", f"/api/history?entity=site&entity_id={sid}")
        self.assertEqual(hist[0]["action"], "delete")
        self.call("POST", f"/api/history/{hist[0]['id']}/restore")
        _, sites = self.call("GET", "/api/sites")
        self.assertIn(sid, [s["id"] for s in sites])

        # restore ของรายการ "create" ต้องถูกปฏิเสธ
        st, _ = self.call("POST", f"/api/history/{hist[-1]['id']}/restore")
        self.assertEqual(st, 400)

    def test_surface_soil_uses_soil_standard_and_unchecked_is_not_green(self):
        self.call("POST", "/api/standards", {"media": "soil", "parameter": "Zn", "max": 100})
        _, a = self.call("POST", "/api/sites", {"name": "ดินผิว", "lat": 13, "lng": 101})
        self.call("POST", "/api/samples", {"site_id": a["id"], "media": "surface_soil",
                                           "results": [{"parameter": "Zn", "value_text": "250"}]})
        _, b = self.call("POST", "/api/sites", {"name": "ไม่มีเกณฑ์", "lat": 13, "lng": 101})
        self.call("POST", "/api/samples", {"site_id": b["id"], "media": "air",
                                           "results": [{"parameter": "XYZ", "value_text": "1"}]})
        _, sites = self.call("GET", "/api/sites")
        by = {s["id"]: s for s in sites}
        self.assertEqual(by[a["id"]]["n_exceed"], 1)       # ดินผิวหน้าใช้เกณฑ์ดิน
        self.assertEqual(by[b["id"]]["n_compared"], 0)     # มีผลแต่ไม่มีเกณฑ์ = ไม่ใช่ "ผ่าน"

    def test_bulk_update_delete_and_batch_restore(self):
        ids = [self.call("POST", "/api/sites", {"name": f"B{i}", "project": "เดิม", "lat": 13, "lng": 101})[1]["id"]
               for i in range(3)]
        st, r = self.call("POST", "/api/sites/bulk", {"ids": ids, "action": "update",
                                                       "fields": {"project": "ใหม่", "code": "ห้ามแก้"}})
        self.assertEqual((st, r["count"]), (200, 3))
        _, sites = self.call("GET", "/api/sites")
        mine = [s for s in sites if s["id"] in ids]
        self.assertEqual({s["project"] for s in mine}, {"ใหม่"})
        self.assertEqual({s["code"] for s in mine}, {None})      # ช่องที่ไม่อนุญาตถูกข้าม
        _, hist = self.call("GET", f"/api/history?batch={r['batch']}")
        self.assertEqual(len(hist), 3)

        st, d = self.call("POST", "/api/sites/bulk", {"ids": ids[:2], "action": "delete"})
        _, sites = self.call("GET", "/api/sites")
        self.assertEqual(len([s for s in sites if s["id"] in ids]), 1)
        self.call("POST", f"/api/history/batch/{d['batch']}/restore")       # ย้อนการลบทั้งชุด
        self.call("POST", f"/api/history/batch/{r['batch']}/restore")       # ย้อนการแก้ทั้งชุด
        _, sites = self.call("GET", "/api/sites")
        mine = [s for s in sites if s["id"] in ids]
        self.assertEqual((len(mine), {s["project"] for s in mine}), (3, {"เดิม"}))

        st, _ = self.call("POST", "/api/sites/bulk", {"ids": ids, "action": "update", "fields": {}})
        self.assertEqual(st, 400)

    def test_undo_whole_import(self):
        csv_text = ("site_code,site_name,lat,lng,sample_date,media,parameter,value\n"
                    "UNDO-1,ก,13,101,2026-01-01,soil,Pb,1\nUNDO-2,ข,13,101,2026-01-01,soil,Pb,2\n")
        self.call("POST", "/api/import/csv", raw=csv_text.encode())
        _, hist = self.call("GET", "/api/history?entity=site")
        batch = next(h["batch"] for h in hist if h["summary"].startswith("UNDO-1"))
        st, r = self.call("POST", f"/api/history/batch/{batch}/restore")
        self.assertEqual((st, r["restored"]), (200, 4))
        _, sites = self.call("GET", "/api/sites")
        self.assertFalse([s for s in sites if (s["code"] or "").startswith("UNDO")])

    def test_old_database_gets_batch_column(self):
        import sqlite3
        path = os.path.join(self.tmp.name, "old.db")
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE history(id INTEGER PRIMARY KEY, at TEXT NOT NULL, user TEXT, action TEXT NOT NULL,"
                  " entity TEXT NOT NULL, entity_id INTEGER, site_id INTEGER, summary TEXT, before TEXT, after TEXT)")
        c.commit(); c.close()
        cur = app.DB_PATH
        try:
            app.DB_PATH = path
            app.init_db()
            c = sqlite3.connect(path)
            try:  # ต้องปิดการเชื่อมต่อ ไม่งั้น Windows ล็อกไฟล์จนลบโฟลเดอร์ชั่วคราวไม่ได้
                cols = [r[1] for r in c.execute("PRAGMA table_info(history)")]
            finally:
                c.close()
            self.assertIn("batch", cols)
        finally:
            app.DB_PATH = cur

    def test_restore_only_reverts_fields_of_that_change(self):
        _, a = self.call("POST", "/api/sites", {"name": "เดิม", "project": "P1", "lat": 13, "lng": 101})
        sid = a["id"]
        self.call("PUT", f"/api/sites/{sid}", {"name": "ชื่อใหม่"})
        self.call("PUT", f"/api/sites/{sid}", {"project": "P2"})
        _, hist = self.call("GET", f"/api/history?entity=site&entity_id={sid}")
        rename = next(h for h in hist if h["action"] == "update" and h["before"]["name"] == "เดิม")
        self.call("POST", f"/api/history/{rename['id']}/restore")
        _, d = self.call("GET", f"/api/sites/{sid}")
        self.assertEqual((d["name"], d["project"]), ("เดิม", "P2"))   # project ที่แก้ทีหลังยังอยู่
        self.call("DELETE", f"/api/sites/{sid}")
        self.call("POST", f"/api/history/{rename['id']}/restore")      # ย้อนการแก้ชื่อซ้ำ ไม่กู้จุดที่ลบ
        _, sites = self.call("GET", "/api/sites")
        self.assertNotIn(sid, [x["id"] for x in sites])

    def test_line_and_circle_geometry(self):
        circle = {"type": "Circle", "center": [101.5, 13.7], "radius": 500}
        st, r = self.call("POST", "/api/sites", {"name": "รัศมี 500 ม.", "lat": 13.7, "lng": 101.5, "geometry": circle})
        self.assertEqual(st, 200)
        line = {"type": "LineString", "coordinates": [[101.5, 13.7], [101.51, 13.71]]}
        self.call("POST", "/api/sites", {"name": "เส้นวัด", "lat": 13.7, "lng": 101.5, "geometry": line})
        st, _ = self.call("POST", "/api/sites", {"name": "เสีย", "geometry": {"type": "Circle", "center": [1, 2], "radius": -1}})
        self.assertEqual(st, 400)
        st, _ = self.call("POST", "/api/sites", {"name": "เสีย", "geometry": "{not json"})
        self.assertEqual(st, 400)
        _, kml = self.call("GET", "/api/export/kml")
        self.assertIn("รัศมี 500 ม.".encode(), kml)
        self.assertIn(b"<LineString>", kml)
        ring = app.circle_ring([101.5, 13.7], 500)
        import math
        dlat = math.radians(ring[0][1] - 13.7) * 6371008.8           # จุดแรกอยู่ทิศเหนือ ห่างเท่ารัศมี
        self.assertAlmostEqual(dlat, 500, delta=1)

    def test_second_server_on_same_port_fails(self):
        # เปิดโปรแกรมซ้ำต้องรู้ว่าพอร์ตไม่ว่าง (บน Windows ถ้าไม่ระวังจะจองซ้อนได้)
        with self.assertRaises(OSError):
            app.make_server("127.0.0.1", self.srv.server_address[1])

    def test_pcd_word_table_import(self):
        raw = make_docx(PCD_DOC)
        payload = {"files": [{"name": "ตาราง.docx", "data": base64.b64encode(raw).decode()}]}
        st, pv = self.call("POST", "/api/import/pcd/preview", payload)
        self.assertEqual(st, 200, pv)
        by = {x["sample_code"]: x for x in pv["samples"]}
        self.assertEqual(sorted(by), ["S1", "W1", "W1-Dup", "W2"])
        w1 = {r["parameter"]: (r["value_text"], r["unit"]) for r in by["W1"]["results"]}
        self.assertEqual(w1["DO"], ("3.27", "mg/L"))
        self.assertEqual(w1["Pb"], ("0.12", "mg/L"))                 # หัวตาราง 2 ชั้น (Heavy metals)
        self.assertEqual(w1["Total Hg"], ("<0.0005", "mg/L"))
        self.assertEqual(w1["Toluene"], ("14", "µg/L"))               # ตารางแนวพารามิเตอร์ (VOCs)
        self.assertEqual(by["W1-Dup"]["results"][0]["value_text"], "15")
        self.assertEqual((by["W1"]["date"], by["W1"]["date_end"], by["W1"]["media"]), ("2026-09-21", "2026-09-23", "surface_water"))
        self.assertEqual((by["W1"]["time"], by["W1"]["appearance"]), ("15.02 น.", "น้ำตาล"))
        self.assertEqual(by["S1"]["media"], "soil")
        self.assertEqual(by["S1"]["new_site"]["province"], "สระแก้ว")  # จากแถวหัวข้ออำเภอ/จังหวัด
        self.assertEqual(by["W1"]["project"], "ทดสอบจังหวัด · พื้นที่ลักลอบทิ้ง")
        std = {(x["media"], x["parameter"]): x for x in pv["standards"]}
        self.assertEqual((std[("surface_water", "pH")]["min"], std[("surface_water", "pH")]["max"]), (5.0, 9.0))
        self.assertEqual(std[("surface_water", "DO")]["min"], 4.0)
        self.assertEqual(std[("surface_water", "Total Hg")]["max"], 0.002)
        self.assertEqual(std[("soil", "Pb")]["max"], 35040.0)
        self.assertTrue(std[("wastewater", "pH")]["reference"].startswith("ประกาศกระทรวงอุตสาหกรรม"))  # ไม่ใช่ "(2) การเกษตร)"

        st, r = self.call("POST", "/api/import/pcd/commit", {"samples": pv["samples"], "standards": pv["standards"]})
        self.assertEqual(st, 200, r)
        self.assertEqual((r["samples"], r["new_sites"]), (4, 3))      # W1 กับ W1-Dup อยู่จุดเดียวกัน
        _, sites = self.call("GET", "/api/sites")
        w1site = next(x for x in sites if x["code"] == "W1")
        self.assertEqual(w1site["n_samples"], 2)
        self.assertIn("Pb", w1site["exceed_params"])                  # 0.12 > 0.05 จากค่ามาตรฐานที่นำเข้า

        _, pv2 = self.call("POST", "/api/import/pcd/preview", payload)   # นำเข้าซ้ำ: จับคู่จุดเดิม + ข้ามตัวอย่างเดิม
        by2 = {x["sample_code"]: x for x in pv2["samples"]}
        self.assertEqual(by2["W1"]["site_id"], w1site["id"])
        self.assertTrue(by2["W1"]["existing_sample_id"])
        self.assertFalse(any(x["include"] for x in pv2["samples"]))

        forced = [dict(x, include=True) for x in pv2["samples"]]          # บังคับเลือกซ้ำ -> เซิร์ฟเวอร์ต้องข้ามเอง
        _, r2 = self.call("POST", "/api/import/pcd/commit", {"samples": forced, "standards": []})
        self.assertEqual((r2["samples"], r2["skipped"]), (0, 4))
        self.call("POST", f"/api/history/batch/{r['batch']}/restore")   # ย้อนการนำเข้าทั้งชุด
        _, sites = self.call("GET", "/api/sites")
        self.assertFalse([x for x in sites if x["code"] in ("W1", "W2", "S1")])
        _, stds = self.call("GET", "/api/standards")
        self.assertFalse([x for x in stds if x["parameter"] == "Total Hg"])

        st, pv3 = self.call("POST", "/api/import/pcd/preview", {"files": [{"name": "x.doc", "data": base64.b64encode(b"\xd0\xcf").decode()}]})
        self.assertEqual(pv3["samples"], [])
        self.assertTrue(pv3["warnings"])

    def test_validation(self):
        st, r = self.call("POST", "/api/sites", {"name": ""})
        self.assertEqual(st, 400)
        st, r = self.call("POST", "/api/sites", {"name": "x", "lat": "abc"})
        self.assertEqual(st, 400)
        st, r = self.call("POST", "/api/samples", {"site_id": 99999})
        self.assertEqual(st, 400)

    def test_photo(self):
        _, r = self.call("POST", "/api/sites", {"name": "รูป", "lat": 13, "lng": 100})
        png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        st, p = self.call("POST", "/api/photos", {"site_id": r["id"], "data": png, "thumb": png, "caption": "ก"})
        self.assertEqual(st, 200)
        st, body = self.call("GET", f"/api/photos/{p['id']}/thumb")
        self.assertEqual(body[:4], b"\x89PNG")
        self.call("DELETE", f"/api/photos/{p['id']}")
        _, d = self.call("GET", f"/api/sites/{r['id']}")
        self.assertEqual(d["photos"], [])

    def test_photo_date_and_sample_must_belong_to_site(self):
        png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        _, a = self.call("POST", "/api/sites", {"name": "A", "lat": 13, "lng": 100})
        _, b = self.call("POST", "/api/sites", {"name": "B", "lat": 13, "lng": 100})
        _, sa = self.call("POST", "/api/samples", {"site_id": a["id"], "media": "soil", "sample_date": "2026-05-27"})
        _, sb = self.call("POST", "/api/samples", {"site_id": b["id"], "media": "soil"})
        st, p = self.call("POST", "/api/photos", {"site_id": a["id"], "data": png, "taken_at": "2026-05-27", "sample_id": sa["id"]})
        self.assertEqual(st, 200)
        _, d = self.call("GET", f"/api/sites/{a['id']}")
        self.assertEqual((d["photos"][0]["taken_at"], d["photos"][0]["sample_id"]), ("2026-05-27", sa["id"]))
        st, _ = self.call("POST", "/api/photos", {"site_id": a["id"], "data": png, "sample_id": sb["id"]})
        self.assertEqual(st, 400)                                   # ตัวอย่างของจุดอื่น
        st, _ = self.call("POST", "/api/photos", {"site_id": a["id"], "data": png, "taken_at": "27/05/2569"})
        self.assertEqual(st, 400)

    def test_kml_kmz_import_and_export(self):
        st, r = self.call("POST", "/api/import/kml", raw=KML.encode(), headers={"X-Filename": "a.kml"})
        self.assertEqual((st, r["added"]), (200, 2))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("doc.kml", KML)
        st, r = self.call("POST", "/api/import/kml", raw=buf.getvalue(), headers={"X-Filename": "a.kmz"})
        self.assertEqual((r["added"], r["skipped"]), (0, 2))  # ซ้ำของเดิม ไม่เพิ่มซ้ำ
        _, sites = self.call("GET", "/api/sites")
        p = next(s for s in sites if s["name"] == "(จุด 1)")
        self.assertEqual((p["category"], p["project"]), ("จุดเก็บน้ำผิวดิน", "ฉะเชิงเทรา"))
        self.assertIn("ท้ายโรงงาน", p["description"])
        self.assertTrue(any(s["geometry"] for s in sites))
        st, kml = self.call("GET", "/api/export/kml")
        self.assertIn("(จุด 1)".encode(), kml)
        self.assertIn(b"<Polygon>", kml)

    def test_csv_import(self):
        csv_text = ("site_code,site_name,lat,lng,sample_date,media,parameter,value,unit\n"
                    "GW-9,บ่อน้ำ,13.5,101.2,2026-01-02,น้ำใต้ดิน,As,0.02,mg/L\n"
                    "GW-9,บ่อน้ำ,13.5,101.2,2026-01-02,น้ำใต้ดิน,Pb,ND,mg/L\n")
        st, r = self.call("POST", "/api/import/csv", raw=csv_text.encode("utf-8-sig"))
        self.assertEqual(st, 200, r)
        self.assertEqual((r["new_sites"], r["samples"], r["results"]), (1, 1, 2))
        _, res = self.call("GET", "/api/results")
        gw = [x for x in res if x["site_code"] == "GW-9"]
        self.assertEqual({x["media"] for x in gw}, {"groundwater"})
        st, csvb = self.call("GET", "/api/export/csv")
        self.assertIn("GW-9", csvb.decode("utf-8-sig"))

    def test_keepalive_does_not_reuse_body(self):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1])
        hdr = {"Content-Type": "application/json"}
        c.request("POST", "/api/sites", json.dumps({"name": "KA", "lat": 1, "lng": 1}), hdr)
        sid = json.loads(c.getresponse().read())["id"]
        c.request("POST", "/api/samples", json.dumps({"site_id": sid, "media": "soil"}), hdr)
        r = c.getresponse()
        self.assertEqual(r.status, 200, r.read())
        c.close()

    def test_backup_and_static(self):
        st, b = self.call("GET", "/api/export/backup")
        self.assertTrue(b.startswith(b"SQLite format 3"))
        st, html = self.call("GET", "/")
        self.assertIn("ฐานข้อมูลจุดเก็บตัวอย่าง".encode(), html)
        st, _ = self.call("GET", "/../app.py")
        self.assertEqual(st, 404)


if __name__ == "__main__":
    unittest.main()
