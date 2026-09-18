#!/usr/bin/env python3
"""โปรแกรม GUI (เปิดในเบราว์เซอร์) สำหรับดูบ่อน้ำบาดาลรอบจุดที่จะประเมิน

รันแล้วเปิดเบราว์เซอร์ไปที่ http://127.0.0.1:8765 อัตโนมัติ ไม่ต้องติดตั้งอะไรเพิ่ม
(ใช้แต่ Python standard library) หน้าเว็บให้เลือกจังหวัด/อำเภอ/ตำบล กดโหลดข้อมูลบ่อ
ครั้งเดียว (ส่วนที่ช้าเพราะต้องไล่เปิดทีละบ่อจากเว็บกรมทรัพยากรน้ำบาดาล) จากนั้นคลิกบนแผนที่
เพื่อกำหนดจุดที่จะประเมิน แล้วปรับวงรัศมีได้ทันทีโดยไม่ต้องโหลดใหม่ (คำนวณระยะทางในเบราว์เซอร์)

ใช้งาน:
  python3 app.py            # เปิดที่พอร์ต 8765 (ค่าเริ่มต้น)
  python3 app.py --port 9000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_dgr_wells as core  # noqa: E402

GUI_HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui.html")

PROVINCE_CACHE: list[tuple[int, str]] | None = None
AMPHOE_CACHE: dict[int, list[tuple[int, str]]] = {}
TAMBON_CACHE: dict[int, list[tuple[int, str]]] = {}
WELLS_LIST_CACHE: dict[int, tuple[float, list[dict]]] = {}  # province_id -> (ts, wells)
COORD_CACHE: dict[int, tuple[float, float] | None] = {}  # well_id -> (lat, lon) or None
WELLS_LIST_TTL = 30 * 60
_lock = threading.Lock()


def get_wells_list_cached(province_id: int) -> list[dict]:
    now = time.time()
    with _lock:
        cached = WELLS_LIST_CACHE.get(province_id)
        if cached and now - cached[0] < WELLS_LIST_TTL:
            return [dict(w) for w in cached[1]]
    wells = core.get_wells_list(province_id)
    with _lock:
        WELLS_LIST_CACHE[province_id] = (now, wells)
    return [dict(w) for w in wells]


def enrich_with_coord_cache(wells: list[dict], max_workers: int = 8) -> list[dict]:
    to_fetch = []
    for w in wells:
        wid = w["well_id"]
        with _lock:
            hit = COORD_CACHE.get(wid)
        if hit is not None:
            w["lat"], w["lon"] = hit
        elif wid in COORD_CACHE:  # cached as "no coord" (None)
            w["lat"], w["lon"] = None, None
        else:
            to_fetch.append(w)

    if to_fetch:
        fetched = core.enrich_with_coords(to_fetch, max_workers=max_workers, progress=False)
        with _lock:
            for w in fetched:
                coords = None
                if w.get("lat") is not None and w.get("lon") is not None:
                    coords = (w["lat"], w["lon"])
                COORD_CACHE[w["well_id"]] = coords
    return wells


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter default logging
        sys.stderr.write("[gui] " + (fmt % args) + "\n")

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, text, status=200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        try:
            if parsed.path in ("/", "/index.html"):
                with open(GUI_HTML_PATH, "r", encoding="utf-8") as f:
                    self._send_html(f.read())

            elif parsed.path == "/api/provinces":
                global PROVINCE_CACHE
                if PROVINCE_CACHE is None:
                    PROVINCE_CACHE = core.list_provinces()
                self._send_json([{"id": i, "name": n} for i, n in PROVINCE_CACHE])

            elif parsed.path == "/api/amphoes":
                province_id = int(qs["province"][0])
                if province_id not in AMPHOE_CACHE:
                    AMPHOE_CACHE[province_id] = core.list_amphoes(province_id)
                self._send_json([{"id": i, "name": n} for i, n in AMPHOE_CACHE[province_id]])

            elif parsed.path == "/api/tambons":
                amphoe_id = int(qs["amphoe"][0])
                if amphoe_id not in TAMBON_CACHE:
                    TAMBON_CACHE[amphoe_id] = core.list_tambons(amphoe_id)
                self._send_json([{"id": i, "name": n} for i, n in TAMBON_CACHE[amphoe_id]])

            elif parsed.path == "/api/wells":
                province_id = int(qs["province"][0])
                amphoe_name = qs.get("amphoe_name", [""])[0]
                tambon_name = qs.get("tambon_name", [""])[0]
                max_wells = int(qs.get("max_wells", ["500"])[0])

                wells = get_wells_list_cached(province_id)
                total_in_province = len(wells)
                if amphoe_name or tambon_name:
                    wells = core.filter_wells(wells, amphoe_name, tambon_name)
                truncated = len(wells) > max_wells
                wells = wells[:max_wells]
                wells = enrich_with_coord_cache(wells)
                wells = [w for w in wells if w.get("lat") is not None]

                self._send_json(
                    {
                        "province_id": province_id,
                        "total_in_province": total_in_province,
                        "matched_before_cap": len(wells) if not truncated else None,
                        "truncated": truncated,
                        "wells": wells,
                    }
                )

            else:
                self._send_json({"error": "not found"}, status=404)

        except Exception as e:  # noqa: BLE001 - surface error to the GUI instead of a blank failure
            self._send_json({"error": str(e)}, status=500)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="ไม่ต้องเปิดเบราว์เซอร์ให้อัตโนมัติ")
    args = ap.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"เปิดโปรแกรมที่: {url}  (กด Ctrl+C เพื่อปิด)")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nปิดโปรแกรมแล้ว")


if __name__ == "__main__":
    main()
