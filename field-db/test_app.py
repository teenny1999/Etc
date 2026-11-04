"""ทดสอบ API: python -m unittest test_app.py"""
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
