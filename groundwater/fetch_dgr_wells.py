#!/usr/bin/env python3
"""ดึงข้อมูลบ่อน้ำบาดาลจากเว็บกรมทรัพยากรน้ำบาดาล (DGR) ระบบสืบค้นบ่อน้ำบาดาล
(http://app.dgr.go.th/newpasutara/xml/search.php) แล้วคำนวณระยะห่างจากจุดที่กำหนด
(เช่น พื้นที่โรงงาน / จุดที่สงสัยว่ามีการลักลอบปล่อยมลพิษ) เพื่อดูว่ารอบๆ จุดนั้น
ในแต่ละรัศมี (กม.) มีบ่อน้ำบาดาลอะไรบ้าง ห่างเท่าไหร่

เว็บต้นทางไม่มีช่องค้นหาแบบ "รัศมีรอบพิกัด" ให้โดยตรง รองรับแค่ค้นตามจังหวัด
(ช่อง filter อำเภอ/ตำบล ของเว็บต้นทาง — ddlProvince/ddlAmphur — มีบั๊กฝั่งเซิร์ฟเวอร์
ส่งไปแล้วได้ผลลัพธ์ 0 แถวเสมอ จึงต้องขอข้อมูลทั้งจังหวัดแล้วมากรองฝั่งเราเอง)
สคริปต์นี้เลยทำงาน 3 ขั้น:
  1. ดึงรายชื่อบ่อ "ทั้งจังหวัด" (จากตาราง tshow.php ที่มีชื่อตำบล/อำเภอกำกับอยู่แล้ว)
  2. กรองเฉพาะบ่อที่อยู่ในอำเภอ/ตำบลที่สนใจ (จับคู่ข้อความ) เพื่อลดจำนวนก่อนดึงพิกัด
  3. ไล่เปิดหน้ารายละเอียดของแต่ละบ่อที่เหลือ (tmapdetail2.php) เพื่อดึงพิกัด lat/lon จริง
     แล้วคำนวณระยะห่างแบบ haversine จากจุดศูนย์กลางที่ผู้ใช้กำหนด

ใช้งาน:
  # ดูรหัสจังหวัดก่อน และดูชื่ออำเภอ/ตำบลที่สะกดถูกต้องตามฐานข้อมูล
  python3 fetch_dgr_wells.py --list-provinces
  python3 fetch_dgr_wells.py --list-amphoes --province 1
  python3 fetch_dgr_wells.py --list-tambons --amphoe 1001

  # ดึงบ่อทั้งจังหวัด กรองเฉพาะอำเภอ/ตำบลที่ใกล้จุดที่จะประเมิน แล้วหาบ่อรอบจุดนั้น
  # ภายใน 10 กม. แบ่งเป็นวง 1/3/5/10 กม.
  python3 fetch_dgr_wells.py \
      --province 1 --amphoe-name คลองสามวา \
      --center-lat 13.8408 --center-lon 100.7414 --site-label "พื้นที่โรงงาน A" \
      --radii 1,3,5,10 --out-json out/wells.json --out-html out/report.html

  # ถ้าจุดที่จะประเมินอยู่ใกล้รอยต่ออำเภอ/ตำบล ให้เว้น --amphoe-name/--tambon-name ไว้
  # (จะดึงพิกัดทั้งจังหวัด ช้ากว่าแต่ไม่พลาดบ่อในอำเภอข้างเคียง — ระวังจังหวัดใหญ่มีเป็นพันบ่อ)
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "http://app.dgr.go.th/newpasutara/xml"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; groundwater-radius-tool/1.0; +for-environmental-assessment)"
}

ROW_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
WELLID_RE = re.compile(r"wellID=(\d+)")
COORD_RE = re.compile(r"circleMarker\(\s*\[\s*([\-0-9.]+)\s*,\s*([\-0-9.]+)\s*\]")
OPTION_RE = re.compile(r'<option value="(\d+)">([^<]+)</option>')


def strip_tags(s: str) -> str:
    return html.unescape(TAG_RE.sub("", s)).strip()


def fetch(url: str, data: bytes | None = None, timeout: int = 20, retries: int = 2) -> str:
    req = urllib.request.Request(url, data=data, headers=HEADERS)
    last_err = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001 - best-effort scraper, report at call site
            last_err = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"fetch failed for {url}: {last_err}")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def list_provinces() -> list[tuple[int, str]]:
    html_doc = fetch(f"{BASE}/search.php")
    # เอาเฉพาะช่วง select ของ "จังหวัด" (select แรกที่มี id=country-dropdown)
    m = re.search(r'id="country-dropdown".*?</select>', html_doc, re.S)
    block = m.group(0) if m else html_doc
    return [(int(v), name.strip()) for v, name in OPTION_RE.findall(block)]


def list_amphoes(province_id: int) -> list[tuple[int, str]]:
    body = urllib.parse.urlencode({"country_id": province_id}).encode()
    doc = fetch(f"{BASE}/ajax/pajax.php", data=body)
    return [(int(v), name.strip()) for v, name in OPTION_RE.findall(doc)]


def list_tambons(amphoe_id: int) -> list[tuple[int, str]]:
    body = urllib.parse.urlencode({"state_id": amphoe_id}).encode()
    doc = fetch(f"{BASE}/ajax/Aajax.php", data=body)
    return [(int(v), name.strip()) for v, name in OPTION_RE.findall(doc)]


def parse_well_rows(table_html: str) -> list[dict]:
    rows = []
    for row_match in re.finditer(r"<tr>(.*?)</tr>", table_html, re.S):
        row = row_match.group(1)
        if "<th" in row:
            continue
        cells = ROW_TD_RE.findall(row)
        if len(cells) < 9:
            continue
        wellid_m = WELLID_RE.search(cells[1])
        if not wellid_m:
            continue
        well_id = int(wellid_m.group(1))
        well_code = strip_tags(cells[1])
        location_text = strip_tags(cells[2])
        alt_m = re.search(r"alt='([^']*)'", cells[3])
        well_type = alt_m.group(1) if alt_m else ""
        depth_m = strip_tags(cells[4])
        yield_m = strip_tags(cells[5])
        water_level_m = strip_tags(cells[6])
        drawdown_m = strip_tags(cells[7])
        capacity_m3d = strip_tags(cells[8])

        tambon = ""
        amphoe = ""
        tm = re.search(r"ต:\s*(\S+)", location_text)
        if tm:
            tambon = tm.group(1)
        am = re.search(r"อ:\s*(\S+)", location_text)
        if am:
            amphoe = am.group(1)

        rows.append(
            {
                "well_id": well_id,
                "well_code": well_code,
                "location_text": location_text,
                "tambon": tambon,
                "amphoe": amphoe,
                "well_type": well_type,
                "depth_m": to_float(depth_m),
                "yield_m3_per_hr": to_float(yield_m),
                "water_level_m": to_float(water_level_m),
                "drawdown_m": to_float(drawdown_m),
                "capacity_m3_per_day": to_float(capacity_m3d),
            }
        )
    return rows


def to_float(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def get_wells_list(province_id: int) -> list[dict]:
    # หมายเหตุ: ddlProvince/ddlAmphur (filter อำเภอ/ตำบล) ของเว็บต้นทางมีบั๊กฝั่งเซิร์ฟเวอร์
    # (ส่งไปแล้วได้ 0 แถวเสมอ) จึงขอมาทั้งจังหวัดแล้วกรองด้วย filter_wells() แทน
    params = {"ddlGeo": province_id, "ddlProvince": "", "ddlAmphur": ""}
    url = f"{BASE}/tshow.php?{urllib.parse.urlencode(params)}"
    doc = fetch(url)
    m = re.search(r"<tbody>(.*?)</tbody>", doc, re.S)
    table_html = m.group(1) if m else doc
    return parse_well_rows(table_html)


def filter_wells(wells: list[dict], amphoe_name: str = "", tambon_name: str = "") -> list[dict]:
    out = wells
    if amphoe_name:
        out = [w for w in out if amphoe_name in w["amphoe"]]
    if tambon_name:
        out = [w for w in out if tambon_name in w["tambon"]]
    return out


def get_well_coords(well_id: int):
    doc = fetch(f"{BASE}/tmapdetail2.php?wellID={well_id}")
    m = COORD_RE.search(doc)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def enrich_with_coords(wells: list[dict], max_workers: int = 8, progress=True) -> list[dict]:
    def worker(w):
        try:
            coords = get_well_coords(w["well_id"])
        except Exception:
            coords = None
        if coords:
            w["lat"], w["lon"] = coords
        else:
            w["lat"], w["lon"] = None, None
        return w

    done = 0
    total = len(wells)
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(worker, w): w for w in wells}
        for fut in as_completed(futures):
            results.append(fut.result())
            done += 1
            if progress and (done % 10 == 0 or done == total):
                print(f"  ...ดึงพิกัดแล้ว {done}/{total} บ่อ", file=sys.stderr)
    return results


def bucket_for_distance(distance_km: float, radii_km: list[float]):
    for r in sorted(radii_km):
        if distance_km <= r:
            return r
    return None


def build_report(args, wells_with_dist: list[dict], radii_km: list[float]):
    data = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "site_label": args.site_label,
        "center": {"lat": args.center_lat, "lon": args.center_lon},
        "radii_km": radii_km,
        "max_radius_km": args.max_radius_km,
        "source": "http://app.dgr.go.th/newpasutara/xml/search.php",
        "wells": wells_with_dist,
    }
    return data


TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "report_template.html")


def write_html_report(data: dict, out_path: str):
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()
    payload = json.dumps(data, ensure_ascii=False)
    out_html = template.replace("__REPORT_DATA__", payload)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_html)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list-provinces", action="store_true", help="แสดงรายชื่อจังหวัด+id แล้วจบ")
    ap.add_argument("--list-amphoes", action="store_true", help="แสดงรายชื่ออำเภอ+id ของ --province แล้วจบ")
    ap.add_argument("--list-tambons", action="store_true", help="แสดงรายชื่อตำบล+id ของ --amphoe แล้วจบ")

    ap.add_argument("--province", type=int, help="รหัสจังหวัด (ddlGeo) ดูได้จาก --list-provinces")
    ap.add_argument("--amphoe", type=int, help="(ใช้กับ --list-tambons เท่านั้น) รหัสอำเภอ ดูได้จาก --list-amphoes")
    ap.add_argument(
        "--amphoe-name",
        default="",
        help="กรองเฉพาะบ่อในอำเภอนี้ (จับคู่เป็นข้อความ ดูชื่อที่สะกดถูกจาก --list-amphoes)",
    )
    ap.add_argument(
        "--tambon-name",
        default="",
        help="กรองเฉพาะบ่อในตำบลนี้ (จับคู่เป็นข้อความ ดูชื่อที่สะกดถูกจาก --list-tambons)",
    )

    ap.add_argument("--center-lat", type=float, help="ละติจูดของจุดที่จะประเมิน (เช่น พื้นที่โรงงาน)")
    ap.add_argument("--center-lon", type=float, help="ลองจิจูดของจุดที่จะประเมิน")
    ap.add_argument("--site-label", default="จุดที่ประเมิน", help="ชื่อจุดอ้างอิง เช่น 'พื้นที่โรงงาน A'")
    ap.add_argument(
        "--radii",
        default="1,3,5,10",
        help="รัศมีที่จะแบ่งวง หน่วยกิโลเมตร คั่นด้วย , (ค่าเริ่มต้น 1,3,5,10)",
    )
    ap.add_argument(
        "--max-radius-km",
        type=float,
        default=None,
        help="ตัดบ่อที่ไกลกว่านี้ทิ้ง (ค่าเริ่มต้น = รัศมีวงนอกสุดใน --radii)",
    )
    ap.add_argument("--max-wells", type=int, default=2000, help="จำกัดจำนวนบ่อสูงสุดที่จะไล่ดึงพิกัด (กันเผลอโหลดหนักเกินไป)")
    ap.add_argument("--max-workers", type=int, default=8, help="จำนวน thread ที่ดึงพิกัดพร้อมกัน")
    ap.add_argument("--out-json", default="groundwater/out/wells.json")
    ap.add_argument("--out-html", default="groundwater/out/report.html")
    args = ap.parse_args()

    if args.list_provinces:
        for pid, name in list_provinces():
            print(f"{pid}\t{name}")
        return

    if args.list_amphoes:
        if not args.province:
            ap.error("--list-amphoes ต้องระบุ --province ด้วย")
        for aid, name in list_amphoes(args.province):
            print(f"{aid}\t{name}")
        return

    if args.list_tambons:
        if not args.amphoe:
            ap.error("--list-tambons ต้องระบุ --amphoe ด้วย")
        for tid, name in list_tambons(args.amphoe):
            print(f"{tid}\t{name}")
        return

    if not args.province:
        ap.error("ต้องระบุ --province (ใช้ --list-provinces เพื่อดูรหัส)")
    if args.center_lat is None or args.center_lon is None:
        ap.error("ต้องระบุ --center-lat และ --center-lon (พิกัดจุดที่จะประเมิน)")

    radii_km = sorted(float(x) for x in args.radii.split(",") if x.strip())
    max_radius_km = args.max_radius_km or (radii_km[-1] if radii_km else 10.0)

    print(f"กำลังดึงรายชื่อบ่อทั้งจังหวัด...", file=sys.stderr)
    wells = get_wells_list(args.province)
    print(f"พบบ่อทั้งหมด {len(wells)} บ่อในจังหวัดนี้", file=sys.stderr)

    if args.amphoe_name or args.tambon_name:
        wells = filter_wells(wells, args.amphoe_name, args.tambon_name)
        print(
            f"กรองด้วยอำเภอ='{args.amphoe_name or '-'}' ตำบล='{args.tambon_name or '-'}' "
            f"เหลือ {len(wells)} บ่อ",
            file=sys.stderr,
        )

    if len(wells) > args.max_wells:
        print(
            f"มากกว่า --max-wells ({args.max_wells}) จะดึงพิกัดแค่ {args.max_wells} บ่อแรก "
            f"— ลองระบุ --amphoe/--tambon ให้แคบลงถ้าต้องการครบทุกบ่อ",
            file=sys.stderr,
        )
        wells = wells[: args.max_wells]

    print("กำลังดึงพิกัดของแต่ละบ่อ (เปิดทีละหน้ารายละเอียด)...", file=sys.stderr)
    wells = enrich_with_coords(wells, max_workers=args.max_workers)

    wells_with_dist = []
    skipped_no_coord = 0
    for w in wells:
        if w.get("lat") is None or w.get("lon") is None:
            skipped_no_coord += 1
            continue
        dist = haversine_km(args.center_lat, args.center_lon, w["lat"], w["lon"])
        if dist > max_radius_km:
            continue
        w["distance_km"] = round(dist, 3)
        w["radius_band_km"] = bucket_for_distance(dist, radii_km)
        wells_with_dist.append(w)

    wells_with_dist.sort(key=lambda w: w["distance_km"])

    if skipped_no_coord:
        print(f"หมายเหตุ: {skipped_no_coord} บ่อดึงพิกัดไม่สำเร็จ (ข้ามไป)", file=sys.stderr)
    print(
        f"พบ {len(wells_with_dist)} บ่อภายในระยะ {max_radius_km} กม. จาก '{args.site_label}'",
        file=sys.stderr,
    )

    data = build_report(args, wells_with_dist, radii_km)

    os.makedirs(os.path.dirname(args.out_json) or ".", exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"บันทึกข้อมูล JSON ที่ {args.out_json}", file=sys.stderr)

    write_html_report(data, args.out_html)
    print(f"สร้างรายงานแผนที่ที่ {args.out_html} (เปิดด้วยเบราว์เซอร์ได้เลย)", file=sys.stderr)


if __name__ == "__main__":
    main()
