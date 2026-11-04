#!/usr/bin/env python3
"""ฐานข้อมูลจุดเก็บตัวอย่างสิ่งแวดล้อม (Field Sample Database)

เซิร์ฟเวอร์เล็กๆ ที่ใช้แค่ Python มาตรฐาน (ไม่ต้อง pip install อะไร)
ข้อมูลทั้งหมดเก็บในไฟล์ SQLite ไฟล์เดียว: data/fielddata.db

    python app.py                 # เปิดใช้งานบนเครื่องตัวเอง แล้วเปิดเบราว์เซอร์ให้อัตโนมัติ
    python app.py --host 0.0.0.0  # ให้เครื่องอื่นในวง LAN เดียวกันเข้าใช้ได้ด้วย
"""
import argparse
import csv
import base64
import html
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import uuid
import webbrowser
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
DEFAULT_DB = os.path.join(HERE, "data", "fielddata.db")
DB_PATH = DEFAULT_DB

MEDIA = {
    "soil": "ดิน",
    "surface_soil": "ดินผิวหน้า",
    "sediment": "ตะกอนดิน",
    "surface_water": "น้ำผิวดิน",
    "groundwater": "น้ำใต้ดิน",
    "wastewater": "น้ำทิ้ง/น้ำเสีย",
    "air": "อากาศ",
    "other": "อื่นๆ",
}

SITE_FIELDS = ["code", "name", "category", "project", "province", "address",
               "description", "lat", "lng", "geometry"]
SAMPLE_FIELDS = ["site_id", "sample_code", "media", "sample_date", "depth",
                 "sampler", "lab", "report_no", "notes"]
RESULT_FIELDS = ["parameter", "value_text", "unit", "method", "note"]
STANDARD_FIELDS = ["media", "parameter", "min", "max", "unit", "reference"]
PHOTO_FIELDS = ["site_id", "sample_id", "caption", "taken_at", "filename"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS sites(
  id INTEGER PRIMARY KEY,
  code TEXT, name TEXT NOT NULL, category TEXT, project TEXT, province TEXT,
  address TEXT, description TEXT, lat REAL, lng REAL, geometry TEXT,
  created_at TEXT, updated_at TEXT, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS samples(
  id INTEGER PRIMARY KEY,
  site_id INTEGER NOT NULL REFERENCES sites(id),
  sample_code TEXT, media TEXT, sample_date TEXT, depth TEXT, sampler TEXT,
  lab TEXT, report_no TEXT, notes TEXT,
  created_at TEXT, updated_at TEXT, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS results(
  id INTEGER PRIMARY KEY,
  sample_id INTEGER NOT NULL REFERENCES samples(id),
  parameter TEXT NOT NULL, value_text TEXT, value REAL, unit TEXT,
  method TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS photos(
  id INTEGER PRIMARY KEY,
  site_id INTEGER NOT NULL REFERENCES sites(id),
  sample_id INTEGER, caption TEXT, taken_at TEXT, filename TEXT,
  mime TEXT, data BLOB, thumb BLOB,
  created_at TEXT, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS standards(
  id INTEGER PRIMARY KEY,
  media TEXT, parameter TEXT NOT NULL, min REAL, max REAL, unit TEXT,
  reference TEXT, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS history(
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL, user TEXT, action TEXT NOT NULL,
  entity TEXT NOT NULL, entity_id INTEGER, site_id INTEGER,
  summary TEXT, before TEXT, after TEXT, batch TEXT);
CREATE INDEX IF NOT EXISTS idx_samples_site ON samples(site_id);
CREATE INDEX IF NOT EXISTS idx_results_sample ON results(sample_id);
CREATE INDEX IF NOT EXISTS idx_photos_site ON photos(site_id);
CREATE INDEX IF NOT EXISTS idx_history_entity ON history(entity, entity_id);
CREATE INDEX IF NOT EXISTS idx_history_site ON history(site_id);
"""


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------- database ---

def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def connect():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = connect()
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(history)")}
    if "batch" not in cols:  # ฐานข้อมูลจากเวอร์ชันก่อน
        con.execute("ALTER TABLE history ADD COLUMN batch TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_history_batch ON history(batch)")
    con.commit()
    con.close()


def clean_text(v):
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def to_float(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        raise ApiError(400, f"ค่าตัวเลขไม่ถูกต้อง: {v}")


def parse_value(text):
    """'0.05' -> 0.05, '>10' -> 10, '<0.005' / 'ND' / 'n.d.' -> None (ต่ำกว่าค่าที่ตรวจวัดได้)"""
    if text is None:
        return None
    t = str(text).strip().replace(",", "")
    if not t or t.startswith("<"):
        return None
    if t.startswith(">"):
        t = t[1:].strip()
    try:
        return float(t)
    except ValueError:
        return None


def row_dict(row, drop=()):
    return {k: row[k] for k in row.keys() if k not in drop} if row else None


def snap_site(con, sid):
    r = con.execute("SELECT * FROM sites WHERE id=?", (sid,)).fetchone()
    return row_dict(r, ("created_at", "updated_at"))


def snap_sample(con, sid):
    r = con.execute("SELECT * FROM samples WHERE id=?", (sid,)).fetchone()
    if not r:
        return None
    d = row_dict(r, ("created_at", "updated_at"))
    d["results"] = [
        {k: x[k] for k in RESULT_FIELDS}
        for x in con.execute("SELECT * FROM results WHERE sample_id=? ORDER BY id", (sid,))
    ]
    return d


def snap_photo(con, pid):
    r = con.execute("SELECT id, site_id, sample_id, caption, taken_at, filename, deleted "
                    "FROM photos WHERE id=?", (pid,)).fetchone()
    return row_dict(r)


def snap_standard(con, sid):
    return row_dict(con.execute("SELECT * FROM standards WHERE id=?", (sid,)).fetchone())


SNAP = {"site": snap_site, "sample": snap_sample, "photo": snap_photo, "standard": snap_standard}


# การทำงานที่แก้หลายรายการในคำสั่งเดียว (แก้/ลบหลายจุด, นำเข้าไฟล์, ย้อนกลับทั้งชุด)
# ใช้รหัสชุดเดียวกันในประวัติ เพื่อให้ดูรวมกันและย้อนกลับได้ในครั้งเดียว
CTX = threading.local()


class batch_scope:
    def __enter__(self):
        CTX.batch = uuid.uuid4().hex[:12]
        return CTX.batch

    def __exit__(self, *exc):
        CTX.batch = None


def log(con, user, action, entity, entity_id, site_id, before, after, summary=None):
    con.execute(
        "INSERT INTO history(at,user,action,entity,entity_id,site_id,summary,before,after,batch) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (now(), user, action, entity, entity_id, site_id, summary,
         json.dumps(before, ensure_ascii=False) if before is not None else None,
         json.dumps(after, ensure_ascii=False) if after is not None else None,
         getattr(CTX, "batch", None)))


def label_site(d):
    if not d:
        return ""
    return " ".join(x for x in [d.get("code"), d.get("name")] if x)


def label_sample(d):
    if not d:
        return ""
    return " ".join(x for x in [d.get("sample_code"), MEDIA.get(d.get("media") or "", d.get("media")),
                                d.get("sample_date")] if x)


# --- writers (ทุกการเขียนผ่านฟังก์ชันเหล่านี้ เพื่อให้บันทึกประวัติครบทุกครั้ง) ---

def site_values(data):
    vals = {f: clean_text(data.get(f)) for f in SITE_FIELDS}
    vals["lat"] = to_float(data.get("lat"))
    vals["lng"] = to_float(data.get("lng"))
    g = data.get("geometry")
    if isinstance(g, (dict, list)):
        g = json.dumps(g)
    vals["geometry"] = clean_text(g)
    if vals["geometry"]:
        try:
            gj = json.loads(vals["geometry"])
            if gj.get("type") == "Circle" and not (float(gj["radius"]) > 0 and len(gj["center"]) == 2):
                raise ValueError
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ApiError(400, "รูปร่าง (geometry) ไม่ถูกต้อง")
    if not vals["name"]:
        raise ApiError(400, "ต้องระบุชื่อจุด/พื้นที่")
    if vals["lat"] is not None and not -90 <= vals["lat"] <= 90:
        raise ApiError(400, "ละติจูดต้องอยู่ระหว่าง -90 ถึง 90")
    if vals["lng"] is not None and not -180 <= vals["lng"] <= 180:
        raise ApiError(400, "ลองจิจูดต้องอยู่ระหว่าง -180 ถึง 180")
    return vals


def create_site(con, user, data, action="create"):
    v = site_values(data)
    t = now()
    cur = con.execute(
        f"INSERT INTO sites({','.join(SITE_FIELDS)},created_at,updated_at) "
        f"VALUES({','.join('?' * len(SITE_FIELDS))},?,?)",
        [v[f] for f in SITE_FIELDS] + [t, t])
    sid = cur.lastrowid
    after = snap_site(con, sid)
    log(con, user, action, "site", sid, sid, None, after, label_site(after))
    return sid


def update_site(con, user, sid, data, action="update"):
    before = snap_site(con, sid)
    if not before:
        raise ApiError(404, "ไม่พบจุดนี้")
    merged = {**before, **{k: data[k] for k in SITE_FIELDS if k in data}}
    v = site_values(merged)
    deleted = int(data.get("deleted", before["deleted"]) or 0)
    con.execute(f"UPDATE sites SET {','.join(f + '=?' for f in SITE_FIELDS)}, deleted=?, updated_at=? "
                "WHERE id=?", [v[f] for f in SITE_FIELDS] + [deleted, now(), sid])
    after = snap_site(con, sid)
    if after != before:
        log(con, user, action, "site", sid, sid, before, after, label_site(after))
    return sid


def sample_values(con, data):
    vals = {f: clean_text(data.get(f)) for f in SAMPLE_FIELDS}
    try:
        vals["site_id"] = int(data.get("site_id"))
    except (TypeError, ValueError):
        raise ApiError(400, "ต้องระบุจุดเก็บตัวอย่าง (site_id)")
    if not con.execute("SELECT 1 FROM sites WHERE id=?", (vals["site_id"],)).fetchone():
        raise ApiError(400, "ไม่พบจุดเก็บตัวอย่างที่ระบุ")
    if vals["sample_date"] and not re.match(r"^\d{4}-\d{2}-\d{2}", vals["sample_date"]):
        raise ApiError(400, "วันที่ต้องอยู่ในรูปแบบ ปปปป-ดด-วว (ค.ศ.)")
    return vals


def write_results(con, sample_id, results):
    con.execute("DELETE FROM results WHERE sample_id=?", (sample_id,))
    for r in results or []:
        p = clean_text(r.get("parameter"))
        if not p:
            continue
        vt = clean_text(r.get("value_text") if "value_text" in r else r.get("value"))
        con.execute("INSERT INTO results(sample_id,parameter,value_text,value,unit,method,note) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (sample_id, p, vt, parse_value(vt), clean_text(r.get("unit")),
                     clean_text(r.get("method")), clean_text(r.get("note"))))


def create_sample(con, user, data, action="create"):
    v = sample_values(con, data)
    t = now()
    cur = con.execute(
        f"INSERT INTO samples({','.join(SAMPLE_FIELDS)},created_at,updated_at) "
        f"VALUES({','.join('?' * len(SAMPLE_FIELDS))},?,?)",
        [v[f] for f in SAMPLE_FIELDS] + [t, t])
    sid = cur.lastrowid
    write_results(con, sid, data.get("results"))
    after = snap_sample(con, sid)
    log(con, user, action, "sample", sid, v["site_id"], None, after, label_sample(after))
    return sid


def update_sample(con, user, sid, data, action="update"):
    before = snap_sample(con, sid)
    if not before:
        raise ApiError(404, "ไม่พบตัวอย่างนี้")
    merged = {**before, **{k: data[k] for k in SAMPLE_FIELDS if k in data}}
    v = sample_values(con, merged)
    deleted = int(data.get("deleted", before["deleted"]) or 0)
    con.execute(f"UPDATE samples SET {','.join(f + '=?' for f in SAMPLE_FIELDS)}, deleted=?, updated_at=? "
                "WHERE id=?", [v[f] for f in SAMPLE_FIELDS] + [deleted, now(), sid])
    if "results" in data:
        write_results(con, sid, data["results"])
    after = snap_sample(con, sid)
    if after != before:
        log(con, user, action, "sample", sid, v["site_id"], before, after, label_sample(after))
    return sid


def update_photo(con, user, pid, data, action="update"):
    before = snap_photo(con, pid)
    if not before:
        raise ApiError(404, "ไม่พบรูปนี้")
    caption = clean_text(data.get("caption", before["caption"]))
    taken = clean_text(data.get("taken_at", before["taken_at"]))
    sample_id = data.get("sample_id", before["sample_id"]) or None
    if sample_id is not None:
        try:
            sample_id = int(sample_id)
        except (TypeError, ValueError):
            raise ApiError(400, "sample_id ไม่ถูกต้อง")
    deleted = int(data.get("deleted", before["deleted"]) or 0)
    con.execute("UPDATE photos SET caption=?, taken_at=?, sample_id=?, deleted=? WHERE id=?",
                (caption, taken, sample_id, deleted, pid))
    after = snap_photo(con, pid)
    if after != before:
        log(con, user, action, "photo", pid, before["site_id"], before, after,
            after.get("caption") or after.get("filename"))


def standard_values(data):
    v = {f: clean_text(data.get(f)) for f in STANDARD_FIELDS}
    v["min"] = to_float(data.get("min"))
    v["max"] = to_float(data.get("max"))
    if not v["parameter"]:
        raise ApiError(400, "ต้องระบุชื่อพารามิเตอร์")
    return v


def save_standard(con, user, sid, data, action=None):
    v = standard_values(data)
    if sid is None:
        cur = con.execute(f"INSERT INTO standards({','.join(STANDARD_FIELDS)}) "
                          f"VALUES({','.join('?' * len(STANDARD_FIELDS))})",
                          [v[f] for f in STANDARD_FIELDS])
        sid = cur.lastrowid
        log(con, user, action or "create", "standard", sid, None, None, snap_standard(con, sid), v["parameter"])
        return sid
    before = snap_standard(con, sid)
    if not before:
        raise ApiError(404, "ไม่พบค่ามาตรฐานนี้")
    deleted = int(data.get("deleted", before["deleted"]) or 0)
    con.execute(f"UPDATE standards SET {','.join(f + '=?' for f in STANDARD_FIELDS)}, deleted=? WHERE id=?",
                [v[f] for f in STANDARD_FIELDS] + [deleted, sid])
    after = snap_standard(con, sid)
    if after != before:
        log(con, user, action or "update", "standard", sid, None, before, after, v["parameter"])
    return sid


def restore(con, user, hid):
    h = con.execute("SELECT * FROM history WHERE id=?", (hid,)).fetchone()
    if not h:
        raise ApiError(404, "ไม่พบรายการประวัตินี้")
    if not h["before"]:
        raise ApiError(400, "รายการนี้เป็นการสร้างใหม่ ไม่มีข้อมูลก่อนหน้าให้ย้อนกลับ "
                            "(ถ้าต้องการเอาออก ให้ลบรายการนั้นแทน)")
    before = json.loads(h["before"])
    after = json.loads(h["after"]) if h["after"] else {}
    # ย้อนเฉพาะช่องที่รายการนี้เปลี่ยน ไม่ทับการแก้ไขอื่นที่เกิดทีหลัง (เช่น ย้อนการแก้ชื่อไม่ควรกู้จุดที่ถูกลบไปแล้วกลับมา)
    data = {k: v for k, v in before.items() if k != "id" and after.get(k) != v}
    if not data:
        return {"ok": True, "unchanged": True}
    ent, eid = h["entity"], h["entity_id"]
    if ent == "sample":
        data.setdefault("site_id", before["site_id"])
    if ent == "standard":
        data = {**(snap_standard(con, eid) or {}), **data}
    if ent == "site":
        update_site(con, user, eid, data, action="restore")
    elif ent == "sample":
        # ถ้าจุดของตัวอย่างนี้ถูกลบไปแล้ว ให้กู้จุดคืนมาด้วย ไม่งั้นจะมองไม่เห็นตัวอย่างที่กู้
        site = snap_site(con, data["site_id"])
        if site and site["deleted"] and data.get("deleted") == 0:
            update_site(con, user, site["id"], {"deleted": 0}, action="restore")
        update_sample(con, user, eid, data, action="restore")
    elif ent == "photo":
        update_photo(con, user, eid, data, action="restore")
    elif ent == "standard":
        save_standard(con, user, eid, data, action="restore")
    else:
        raise ApiError(400, "ย้อนกลับรายการประเภทนี้ไม่ได้")
    return {"ok": True}


def restore_batch(con, user, batch):
    rows = con.execute("SELECT * FROM history WHERE batch=? ORDER BY id DESC", (batch,)).fetchall()
    if not rows:
        raise ApiError(404, "ไม่พบชุดการเปลี่ยนแปลงนี้")
    n = 0
    with batch_scope():
        for h in rows:  # ย้อนจากรายการล่าสุดไปเก่าสุด สถานะสุดท้ายจึงเท่ากับก่อนทำชุดนี้
            if h["before"]:
                restore(con, user, h["id"])
            elif h["entity"] == "site":      # รายการที่ชุดนี้สร้างขึ้น (เช่น นำเข้า) -> เอาออก
                update_site(con, user, h["entity_id"], {"deleted": 1}, action="restore")
            elif h["entity"] == "sample":
                update_sample(con, user, h["entity_id"], {"deleted": 1}, action="restore")
            else:
                continue
            n += 1
    return {"ok": True, "restored": n}


BULK_FIELDS = ["project", "category", "province", "address", "description"]


def bulk_sites(con, user, data):
    try:
        ids = sorted({int(i) for i in data.get("ids") or []})
    except (TypeError, ValueError):
        raise ApiError(400, "รายการจุดไม่ถูกต้อง")
    if not ids:
        raise ApiError(400, "ยังไม่ได้เลือกจุด")
    action = data.get("action")
    fields = {k: v for k, v in (data.get("fields") or {}).items() if k in BULK_FIELDS}
    if action == "update" and not fields:
        raise ApiError(400, "ยังไม่ได้เลือกช่องที่จะแก้ไข")
    if action not in ("update", "delete"):
        raise ApiError(400, "action ต้องเป็น update หรือ delete")
    with batch_scope() as b:
        for sid in ids:
            if action == "delete":
                update_site(con, user, sid, {"deleted": 1}, action="delete")
            else:
                update_site(con, user, sid, fields)
    return {"ok": True, "count": len(ids), "batch": b}


# ---------------------------------------------------------------- queries ---

def load_standards(con):
    out = {}
    for s in con.execute("SELECT * FROM standards WHERE deleted=0"):
        out[((s["media"] or ""), s["parameter"].strip().lower())] = dict(s)
    return out


# ประเภทที่ไม่มีค่ามาตรฐานของตัวเอง ให้ใช้ของประเภทแม่ (เช่น ดินผิวหน้า -> ดิน)
MEDIA_FALLBACK = {"surface_soil": "soil"}


def find_standard(stds, media, parameter):
    key = (parameter or "").strip().lower()
    media = media or ""
    return (stds.get((media, key)) or stds.get((MEDIA_FALLBACK.get(media, ""), key))
            or stds.get(("", key)))


def exceed_flag(std, value):
    """1 = เกินค่าสูงสุด, -1 = ต่ำกว่าค่าต่ำสุด, 0 = ผ่าน, None = ไม่มีมาตรฐาน/ไม่มีค่าตัวเลข"""
    if not std or value is None:
        return None
    if std["max"] is not None and value > std["max"]:
        return 1
    if std["min"] is not None and value < std["min"]:
        return -1
    if std["max"] is None and std["min"] is None:
        return None
    return 0


def all_results(con, site_id=None):
    stds = load_standards(con)
    q = """SELECT r.id, r.sample_id, r.parameter, r.value_text, r.value, r.unit, r.method, r.note,
                  s.site_id, s.sample_code, s.media, s.sample_date, s.depth, s.sampler, s.lab,
                  t.code AS site_code, t.name AS site_name, t.project, t.province, t.category
           FROM results r JOIN samples s ON s.id=r.sample_id JOIN sites t ON t.id=s.site_id
           WHERE s.deleted=0 AND t.deleted=0"""
    args = []
    if site_id is not None:
        q += " AND s.site_id=?"
        args.append(site_id)
    q += " ORDER BY s.sample_date DESC, s.id DESC, r.id"
    out = []
    for r in con.execute(q, args):
        d = dict(r)
        std = find_standard(stds, d["media"], d["parameter"])
        d["std_min"] = std["min"] if std else None
        d["std_max"] = std["max"] if std else None
        d["std_unit"] = std["unit"] if std else None
        d["std_ref"] = std["reference"] if std else None
        d["exceed"] = exceed_flag(std, d["value"])
        out.append(d)
    return out


def list_sites(con):
    sites = {r["id"]: dict(r) for r in con.execute(
        "SELECT * FROM sites WHERE deleted=0 ORDER BY COALESCE(code,''), name")}
    for s in sites.values():
        s.update(n_samples=0, n_photos=0, last_date=None, media=[], n_exceed=0, n_compared=0, exceed_params=[])
    for r in con.execute("SELECT site_id, COUNT(*) n, MAX(sample_date) d, GROUP_CONCAT(DISTINCT media) m "
                         "FROM samples WHERE deleted=0 GROUP BY site_id"):
        if r["site_id"] in sites:
            sites[r["site_id"]].update(n_samples=r["n"], last_date=r["d"],
                                       media=[m for m in (r["m"] or "").split(",") if m])
    for r in con.execute("SELECT site_id, COUNT(*) n FROM photos WHERE deleted=0 GROUP BY site_id"):
        if r["site_id"] in sites:
            sites[r["site_id"]]["n_photos"] = r["n"]
    for r in all_results(con):
        if r["exceed"] is not None and r["site_id"] in sites:
            sites[r["site_id"]]["n_compared"] += 1
        if r["exceed"] and r["site_id"] in sites:
            s = sites[r["site_id"]]
            s["n_exceed"] += 1
            if r["parameter"] not in s["exceed_params"]:
                s["exceed_params"].append(r["parameter"])
    return list(sites.values())


def site_detail(con, sid):
    site = con.execute("SELECT * FROM sites WHERE id=?", (sid,)).fetchone()
    if not site:
        raise ApiError(404, "ไม่พบจุดนี้")
    d = dict(site)
    res = all_results(con, sid)
    by_sample = {}
    for r in res:
        by_sample.setdefault(r["sample_id"], []).append(r)
    d["samples"] = []
    for s in con.execute("SELECT * FROM samples WHERE site_id=? AND deleted=0 "
                         "ORDER BY sample_date DESC, id DESC", (sid,)):
        sd = dict(s)
        sd["results"] = by_sample.get(s["id"], [])
        d["samples"].append(sd)
    d["photos"] = [dict(p) for p in con.execute(
        "SELECT id, sample_id, caption, taken_at, filename, created_at FROM photos "
        "WHERE site_id=? AND deleted=0 ORDER BY COALESCE(taken_at, created_at) DESC, id DESC", (sid,))]
    return d


def history(con, qs):
    q = "SELECT * FROM history WHERE 1=1"
    args = []
    if "site_id" in qs:
        q += " AND site_id=?"
        args.append(int(qs["site_id"]))
    if "entity" in qs:
        q += " AND entity=?"
        args.append(qs["entity"])
    if "entity_id" in qs:
        q += " AND entity_id=?"
        args.append(int(qs["entity_id"]))
    if "batch" in qs:
        q += " AND batch=?"
        args.append(qs["batch"])
    q += " ORDER BY id DESC LIMIT ?"
    args.append(min(int(qs.get("limit", 300)), 5000))
    out = []
    for h in con.execute(q, args):
        d = dict(h)
        d["before"] = json.loads(d["before"]) if d["before"] else None
        d["after"] = json.loads(d["after"]) if d["after"] else None
        out.append(d)
    return out


# ---------------------------------------------------------- import/export ---

KML_NS = re.compile(r"^\{[^}]*\}")


def _tag(el):
    return KML_NS.sub("", el.tag)


def _child(el, name):
    for c in el:
        if _tag(c) == name:
            return c
    return None


def _text(el, name):
    c = _child(el, name)
    return (c.text or "").strip() if c is not None and c.text else ""


def _coords(text):
    pts = []
    for tok in (text or "").split():
        parts = tok.split(",")
        if len(parts) >= 2:
            try:
                pts.append([float(parts[0]), float(parts[1])])
            except ValueError:
                pass
    return pts


def _strip_html(s):
    s = re.sub(r"<br\s*/?>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"[ \t]+", " ", html.unescape(s)).strip()


def _geometries(pm):
    """คืนค่า list ของ GeoJSON geometry ทั้งหมดใน Placemark (รวม MultiGeometry)"""
    out = []
    for el in pm.iter():
        t = _tag(el)
        if t == "Point":
            pts = _coords(_text(el, "coordinates"))
            if pts:
                out.append({"type": "Point", "coordinates": pts[0]})
        elif t == "LineString":
            pts = _coords(_text(el, "coordinates"))
            if len(pts) >= 2:
                out.append({"type": "LineString", "coordinates": pts})
        elif t == "Polygon":
            rings = []
            for ring in el.iter():
                if _tag(ring) == "LinearRing":
                    pts = _coords(_text(ring, "coordinates"))
                    if len(pts) >= 3:
                        rings.append(pts)
            if rings:
                out.append({"type": "Polygon", "coordinates": rings})
    return out


def _centroid(geom):
    if geom["type"] == "Point":
        return geom["coordinates"]
    pts = geom["coordinates"][0] if geom["type"] == "Polygon" else geom["coordinates"]
    return [sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)]


def parse_kml(raw, filename):
    if filename.lower().endswith(".kmz") or raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".kml")]
            if not names:
                raise ApiError(400, "ไม่พบไฟล์ .kml ใน .kmz")
            names.sort(key=lambda n: (n.lower() != "doc.kml", n.count("/"), n))
            raw = z.read(names[0])
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise ApiError(400, f"อ่านไฟล์ KML ไม่ได้: {e}")

    found = []

    def walk(el, path):
        for c in el:
            t = _tag(c)
            if t in ("Document", "Folder"):
                name = _text(c, "name")
                walk(c, path + ([name] if name else []))
            elif t == "Placemark":
                geoms = _geometries(c)
                if not geoms:
                    continue
                geom = geoms[0] if len(geoms) == 1 else {"type": "GeometryCollection", "geometries": geoms}
                main = next((g for g in geoms if g["type"] != "Point"), geoms[0])
                lng, lat = _centroid(main)
                found.append({
                    "name": _text(c, "name") or "(ไม่มีชื่อ)",
                    "description": _strip_html(_text(c, "description")) or None,
                    "category": path[-1] if path else None,
                    "project": " / ".join(path[:-1]) if len(path) > 1 else (path[0] if path else None),
                    "lat": lat, "lng": lng,
                    "geometry": None if geom["type"] == "Point" else json.dumps(geom),
                })
            else:
                walk(c, path)

    walk(root, [])
    return found


def import_kml(con, user, raw, filename):
    items = parse_kml(raw, filename)
    existing = {(r["name"], round(r["lat"] or 0, 6), round(r["lng"] or 0, 6))
                for r in con.execute("SELECT name, lat, lng FROM sites WHERE deleted=0")}
    added = skipped = 0
    for it in items:
        key = (it["name"], round(it["lat"], 6), round(it["lng"], 6))
        if key in existing:
            skipped += 1
            continue
        existing.add(key)
        create_site(con, user, it, action="import")
        added += 1
    return {"found": len(items), "added": added, "skipped": skipped}


CSV_ALIASES = {
    "site_code": ["site_code", "code", "รหัสจุด"],
    "site_name": ["site_name", "name", "ชื่อจุด"],
    "lat": ["lat", "latitude", "ละติจูด"],
    "lng": ["lng", "lon", "long", "longitude", "ลองจิจูด"],
    "project": ["project", "โครงการ"],
    "province": ["province", "จังหวัด"],
    "category": ["category", "ประเภทจุด"],
    "sample_code": ["sample_code", "รหัสตัวอย่าง"],
    "sample_date": ["sample_date", "date", "วันที่"],
    "media": ["media", "ประเภทตัวอย่าง"],
    "depth": ["depth", "ความลึก"],
    "sampler": ["sampler", "ผู้เก็บ"],
    "lab": ["lab", "ห้องปฏิบัติการ"],
    "report_no": ["report_no", "เลขที่รายงาน"],
    "parameter": ["parameter", "พารามิเตอร์", "สาร"],
    "value": ["value", "value_text", "ค่า", "ผล"],
    "unit": ["unit", "หน่วย"],
    "method": ["method", "วิธีวิเคราะห์"],
}
MEDIA_BY_LABEL = {v: k for k, v in MEDIA.items()}


def import_csv(con, user, raw):
    text = raw.decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ApiError(400, "ไฟล์ CSV ว่าง")
    headers = {h.strip().lower(): h for h in rows[0].keys() if h}
    col = {}
    for key, names in CSV_ALIASES.items():
        for n in names:
            if n.lower() in headers:
                col[key] = headers[n.lower()]
                break
    if "site_code" not in col and "site_name" not in col:
        raise ApiError(400, "CSV ต้องมีคอลัมน์ site_code หรือ site_name")

    def get(row, key):
        return clean_text(row.get(col[key])) if key in col else None

    sites_by_code = {}
    for r in con.execute("SELECT id, code, name FROM sites WHERE deleted=0"):
        if r["code"]:
            sites_by_code.setdefault(r["code"].lower(), r["id"])
        sites_by_code.setdefault("name:" + r["name"].lower(), r["id"])

    groups = {}
    new_sites = 0
    for i, row in enumerate(rows, start=2):
        code, name = get(row, "site_code"), get(row, "site_name")
        key = code.lower() if code else "name:" + (name or "").lower()
        if not code and not name:
            continue
        sid = sites_by_code.get(key)
        if sid is None:
            if get(row, "lat") is None or get(row, "lng") is None:
                raise ApiError(400, f"แถว {i}: ไม่พบจุด '{code or name}' ในฐานข้อมูล "
                                    "และไม่มีพิกัด lat/lng ให้สร้างจุดใหม่")
            sid = create_site(con, user, {
                "code": code, "name": name or code, "lat": get(row, "lat"), "lng": get(row, "lng"),
                "project": get(row, "project"), "province": get(row, "province"),
                "category": get(row, "category")}, action="import")
            sites_by_code[key] = sid
            new_sites += 1
        media = get(row, "media")
        media = MEDIA_BY_LABEL.get(media, media)
        skey = (sid, get(row, "sample_code"), get(row, "sample_date"), media, get(row, "depth"))
        g = groups.setdefault(skey, {
            "site_id": sid, "sample_code": skey[1], "sample_date": skey[2], "media": media,
            "depth": skey[4], "sampler": get(row, "sampler"), "lab": get(row, "lab"),
            "report_no": get(row, "report_no"), "results": []})
        if get(row, "parameter"):
            g["results"].append({"parameter": get(row, "parameter"), "value_text": get(row, "value"),
                                 "unit": get(row, "unit"), "method": get(row, "method")})
    n_results = 0
    for g in groups.values():
        create_sample(con, user, g, action="import")
        n_results += len(g["results"])
    return {"rows": len(rows), "new_sites": new_sites, "samples": len(groups), "results": n_results}


def circle_ring(center, radius, n=72):
    """จุดรอบวงกลมรัศมี radius เมตร รอบ center [lng, lat] บนทรงกลม"""
    import math
    lng0, lat0 = map(math.radians, center)
    d = radius / 6371008.8
    pts = []
    for i in range(n + 1):
        b = 2 * math.pi * i / n
        lat = math.asin(math.sin(lat0) * math.cos(d) + math.cos(lat0) * math.sin(d) * math.cos(b))
        lng = lng0 + math.atan2(math.sin(b) * math.sin(d) * math.cos(lat0), math.cos(d) - math.sin(lat0) * math.sin(lat))
        pts.append([round(math.degrees(lng), 7), round(math.degrees(lat), 7)])
    return pts


def export_kml(con):
    sites = list_sites(con)
    res = {}
    for r in all_results(con):
        res.setdefault(r["site_id"], []).append(r)
    esc = html.escape
    by_project = {}
    for s in sites:
        by_project.setdefault(s["project"] or "(ไม่ระบุโครงการ)", []).append(s)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
           f"<name>ฐานข้อมูลจุดเก็บตัวอย่าง ({esc(now()[:10])})</name>",
           '<Style id="ok"><IconStyle><color>ff00c000</color><Icon><href>'
           'http://maps.google.com/mapfiles/kml/paddle/grn-circle.png</href></Icon></IconStyle></Style>',
           '<Style id="bad"><IconStyle><color>ff0000ff</color><Icon><href>'
           'http://maps.google.com/mapfiles/kml/paddle/red-circle.png</href></Icon></IconStyle></Style>',
           '<Style id="none"><IconStyle><Icon><href>'
           'http://maps.google.com/mapfiles/kml/paddle/ylw-circle.png</href></Icon></IconStyle>'
           '<LineStyle><color>ff00ffff</color><width>2</width></LineStyle>'
           '<PolyStyle><color>4000ffff</color></PolyStyle></Style>']

    def coords(pts):
        return " ".join(f"{p[0]},{p[1]},0" for p in pts)

    def geom_kml(g):
        t = g["type"]
        if t == "Point":
            return f"<Point><coordinates>{coords([g['coordinates']])}</coordinates></Point>"
        if t == "LineString":
            return f"<LineString><coordinates>{coords(g['coordinates'])}</coordinates></LineString>"
        if t == "Polygon":
            rings = g["coordinates"]
            s = f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{coords(rings[0])}</coordinates>" \
                "</LinearRing></outerBoundaryIs>"
            for r in rings[1:]:
                s += f"<innerBoundaryIs><LinearRing><coordinates>{coords(r)}</coordinates></LinearRing>" \
                     "</innerBoundaryIs>"
            return s + "</Polygon>"
        if t == "GeometryCollection":
            return "<MultiGeometry>" + "".join(geom_kml(x) for x in g["geometries"]) + "</MultiGeometry>"
        if t == "Circle":  # KML ไม่มีวงกลม ส่งออกเป็นรูปหลายเหลี่ยม 72 มุม
            return geom_kml({"type": "Polygon", "coordinates": [circle_ring(g["center"], float(g["radius"]))]})
        return ""

    for proj, items in sorted(by_project.items()):
        out.append(f"<Folder><name>{esc(proj)}</name>")
        for s in items:
            desc = [f"<b>{esc(label_site(s))}</b>"]
            for k, lab in [("category", "ประเภท"), ("province", "จังหวัด"), ("address", "ที่ตั้ง"),
                           ("description", "รายละเอียด")]:
                if s.get(k):
                    desc.append(f"{lab}: {esc(s[k])}")
            rows = res.get(s["id"], [])
            if rows:
                desc.append("<table border='1' cellpadding='3' style='border-collapse:collapse'>"
                            "<tr><th>วันที่</th><th>ตัวอย่าง</th><th>พารามิเตอร์</th><th>ค่า</th></tr>")
                for r in rows[:60]:
                    color = " style='color:red;font-weight:bold'" if r["exceed"] else ""
                    desc.append(f"<tr><td>{esc(r['sample_date'] or '')}</td>"
                                f"<td>{esc(MEDIA.get(r['media'] or '', r['media'] or ''))}</td>"
                                f"<td>{esc(r['parameter'])}</td>"
                                f"<td{color}>{esc(r['value_text'] or '')} {esc(r['unit'] or '')}</td></tr>")
                desc.append("</table>")
            style = "bad" if s["n_exceed"] else ("ok" if rows else "none")
            geoms = []
            if s["lat"] is not None and s["lng"] is not None:
                geoms.append(geom_kml({"type": "Point", "coordinates": [s["lng"], s["lat"]]}))
            if s["geometry"]:
                try:
                    geoms.append(geom_kml(json.loads(s["geometry"])))
                except (ValueError, KeyError, TypeError):
                    pass
            if not geoms:
                continue
            g = geoms[0] if len(geoms) == 1 else "<MultiGeometry>" + "".join(geoms) + "</MultiGeometry>"
            out.append(f"<Placemark><name>{esc(s['code'] or s['name'])}</name>"
                       f"<description><![CDATA[{'<br>'.join(desc)}]]></description>"
                       f"<styleUrl>#{style}</styleUrl>{g}</Placemark>")
        out.append("</Folder>")
    out.append("</Document></kml>")
    return "\n".join(out).encode("utf-8")


def export_csv(con):
    buf = io.StringIO()
    cols = ["site_code", "site_name", "project", "province", "category", "sample_code", "sample_date",
            "media", "depth", "sampler", "lab", "parameter", "value_text", "unit", "method",
            "std_min", "std_max", "exceed"]
    w = csv.writer(buf)
    w.writerow(cols)
    for r in all_results(con):
        w.writerow(["" if r.get(c) is None else r.get(c) for c in cols])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def backup_bytes():
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src = connect()
        dst = sqlite3.connect(tmp)
        src.backup(dst)
        dst.close()
        src.close()
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        os.remove(tmp)


def decode_data_url(s):
    if not s:
        return None, None
    m = re.match(r"^data:([\w/+.-]+);base64,(.*)$", s, re.S)
    if not m:
        raise ApiError(400, "รูปแบบไฟล์รูปไม่ถูกต้อง")
    return m.group(1), base64.b64decode(m.group(2))


# ------------------------------------------------------------------- HTTP ---

ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


@route("GET", "/api/meta")
def r_meta(h, con):
    params = [r[0] for r in con.execute(
        "SELECT parameter FROM (SELECT parameter FROM results UNION SELECT parameter FROM standards "
        "WHERE deleted=0) ORDER BY lower(parameter)")]
    units = {}
    for r in con.execute("SELECT parameter, unit, COUNT(*) n FROM results WHERE unit IS NOT NULL "
                         "GROUP BY lower(parameter), unit ORDER BY n"):
        units[r["parameter"].lower()] = r["unit"]
    distinct = lambda col: [r[0] for r in con.execute(
        f"SELECT DISTINCT {col} FROM sites WHERE deleted=0 AND {col} IS NOT NULL ORDER BY {col}")]
    return {"media": MEDIA, "parameters": params, "units": units,
            "projects": distinct("project"), "provinces": distinct("province"),
            "categories": distinct("category"),
            "samplers": [r[0] for r in con.execute(
                "SELECT DISTINCT sampler FROM samples WHERE sampler IS NOT NULL ORDER BY sampler")],
            "labs": [r[0] for r in con.execute(
                "SELECT DISTINCT lab FROM samples WHERE lab IS NOT NULL ORDER BY lab")],
            "db_path": DB_PATH}


@route("GET", "/api/sites")
def r_sites(h, con):
    return list_sites(con)


@route("POST", "/api/sites")
def r_site_create(h, con):
    return {"id": create_site(con, h.user, h.body())}


@route("GET", r"/api/sites/(\d+)")
def r_site_get(h, con, sid):
    return site_detail(con, int(sid))


@route("PUT", r"/api/sites/(\d+)")
def r_site_update(h, con, sid):
    data = h.body()
    data.pop("deleted", None)
    return {"id": update_site(con, h.user, int(sid), data)}


@route("DELETE", r"/api/sites/(\d+)")
def r_site_delete(h, con, sid):
    update_site(con, h.user, int(sid), {"deleted": 1}, action="delete")
    return {"ok": True}


@route("POST", "/api/samples")
def r_sample_create(h, con):
    return {"id": create_sample(con, h.user, h.body())}


@route("PUT", r"/api/samples/(\d+)")
def r_sample_update(h, con, sid):
    data = h.body()
    data.pop("deleted", None)
    return {"id": update_sample(con, h.user, int(sid), data)}


@route("DELETE", r"/api/samples/(\d+)")
def r_sample_delete(h, con, sid):
    update_sample(con, h.user, int(sid), {"deleted": 1}, action="delete")
    return {"ok": True}


@route("GET", "/api/results")
def r_results(h, con):
    return all_results(con)


@route("POST", "/api/photos")
def r_photo_create(h, con):
    d = h.body()
    try:
        site_id = int(d.get("site_id"))
    except (TypeError, ValueError):
        raise ApiError(400, "ต้องระบุ site_id")
    if not con.execute("SELECT 1 FROM sites WHERE id=?", (site_id,)).fetchone():
        raise ApiError(400, "ไม่พบจุดที่ระบุ")
    mime, data = decode_data_url(d.get("data"))
    if not data:
        raise ApiError(400, "ไม่มีข้อมูลรูป")
    _, thumb = decode_data_url(d.get("thumb"))
    sample_id = d.get("sample_id") or None
    if sample_id is not None and not con.execute("SELECT 1 FROM samples WHERE id=? AND site_id=?",
                                                 (sample_id, site_id)).fetchone():
        raise ApiError(400, "ตัวอย่างที่ระบุไม่ได้อยู่ในจุดนี้")
    taken = clean_text(d.get("taken_at"))
    if taken and not re.match(r"^\d{4}-\d{2}-\d{2}", taken):
        raise ApiError(400, "วันที่ถ่ายต้องอยู่ในรูปแบบ ปปปป-ดด-วว (ค.ศ.)")
    cur = con.execute("INSERT INTO photos(site_id,sample_id,caption,taken_at,filename,mime,data,thumb,created_at) "
                      "VALUES(?,?,?,?,?,?,?,?,?)",
                      (site_id, sample_id, clean_text(d.get("caption")),
                       taken, clean_text(d.get("filename")), mime, data, thumb, now()))
    pid = cur.lastrowid
    after = snap_photo(con, pid)
    log(con, h.user, "create", "photo", pid, site_id, None, after, after.get("caption") or after.get("filename"))
    return {"id": pid}


@route("GET", r"/api/photos/(\d+)(/thumb)?")
def r_photo_get(h, con, pid, thumb):
    r = con.execute("SELECT mime, data, thumb FROM photos WHERE id=?", (int(pid),)).fetchone()
    if not r:
        raise ApiError(404, "ไม่พบรูป")
    body = (r["thumb"] if thumb and r["thumb"] else r["data"])
    h.send_bytes(body, r["mime"] or "image/jpeg", cache=True)


@route("PUT", r"/api/photos/(\d+)")
def r_photo_update(h, con, pid):
    data = h.body()
    data.pop("deleted", None)
    update_photo(con, h.user, int(pid), data)
    return {"ok": True}


@route("DELETE", r"/api/photos/(\d+)")
def r_photo_delete(h, con, pid):
    update_photo(con, h.user, int(pid), {"deleted": 1}, action="delete")
    return {"ok": True}


@route("GET", "/api/standards")
def r_standards(h, con):
    return [dict(r) for r in con.execute(
        "SELECT * FROM standards WHERE deleted=0 ORDER BY COALESCE(media,''), lower(parameter)")]


@route("POST", "/api/standards")
def r_standard_create(h, con):
    return {"id": save_standard(con, h.user, None, h.body())}


@route("PUT", r"/api/standards/(\d+)")
def r_standard_update(h, con, sid):
    data = h.body()
    data.pop("deleted", None)
    return {"id": save_standard(con, h.user, int(sid), data)}


@route("DELETE", r"/api/standards/(\d+)")
def r_standard_delete(h, con, sid):
    sid = int(sid)
    cur = snap_standard(con, sid)
    if not cur:
        raise ApiError(404, "ไม่พบค่ามาตรฐานนี้")
    save_standard(con, h.user, sid, {**cur, "deleted": 1}, action="delete")
    return {"ok": True}


@route("GET", "/api/history")
def r_history(h, con):
    return history(con, h.query())


@route("POST", r"/api/history/(\d+)/restore")
def r_restore(h, con, hid):
    return restore(con, h.user, int(hid))


@route("POST", r"/api/history/batch/(\w+)/restore")
def r_restore_batch(h, con, batch):
    return restore_batch(con, h.user, batch)


@route("POST", "/api/sites/bulk")
def r_sites_bulk(h, con):
    return bulk_sites(con, h.user, h.body())


@route("POST", "/api/import/kml")
def r_import_kml(h, con):
    with batch_scope():
        return import_kml(con, h.user, h.raw(), h.filename())


@route("POST", "/api/import/csv")
def r_import_csv(h, con):
    with batch_scope():
        return import_csv(con, h.user, h.raw())


@route("GET", "/api/export/kml")
def r_export_kml(h, con):
    h.send_bytes(export_kml(con), "application/vnd.google-earth.kml+xml",
                 download=f"fielddata-{now()[:10]}.kml")


@route("GET", "/api/export/csv")
def r_export_csv(h, con):
    h.send_bytes(export_csv(con), "text/csv; charset=utf-8", download=f"results-{now()[:10]}.csv")


@route("GET", "/api/export/backup")
def r_export_backup(h, con):
    h.send_bytes(backup_bytes(), "application/x-sqlite3", download=f"fielddata-backup-{now()[:10]}.db")


MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
        ".ico": "image/x-icon", ".json": "application/json"}


class Handler(BaseHTTPRequestHandler):
    server_version = "FieldDB/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if os.environ.get("FIELDDB_QUIET"):
            return
        sys.stderr.write("[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), fmt % args))

    # -- helpers used by routes
    @property
    def user(self):
        return clean_text(unquote(self.headers.get("X-User", ""))) or "ไม่ระบุชื่อ"

    def filename(self):
        return unquote(self.headers.get("X-Filename", "upload"))

    def raw(self):
        if self._raw is None:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 200 * 1024 * 1024:
                raise ApiError(413, "ไฟล์ใหญ่เกินไป")
            self._raw = self.rfile.read(n) if n else b""
        return self._raw

    def body(self):
        try:
            d = json.loads(self.raw() or b"{}")
        except ValueError:
            raise ApiError(400, "ข้อมูล JSON ไม่ถูกต้อง")
        if not isinstance(d, dict):
            raise ApiError(400, "ข้อมูล JSON ต้องเป็น object")
        return d

    def query(self):
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def send_bytes(self, body, ctype, status=200, download=None, cache=False):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if download:
            self.send_header("Content-Disposition", f"attachment; filename=\"{download}\"")
        self.send_header("Cache-Control", "private, max-age=86400" if cache else "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self._sent = True

    def send_json(self, obj, status=200):
        self.send_bytes(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                        "application/json; charset=utf-8", status)

    # -- dispatch
    def handle_any(self):
        self._raw = None  # keep-alive: handler ตัวเดียวรับหลาย request ต้องล้าง body เก่าทุกครั้ง
        try:
            self.dispatch()
        except (BrokenPipeError, ConnectionResetError):
            pass  # เบราว์เซอร์ปิดการเชื่อมต่อไปก่อน ไม่ใช่ข้อผิดพลาด

    def dispatch(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            return self.handle_api(path)
        if self.command not in ("GET", "HEAD"):
            return self.send_json({"error": "not found"}, 404)
        rel = "index.html" if path in ("/", "") else unquote(path.lstrip("/"))
        full = os.path.realpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(os.path.realpath(STATIC_DIR) + os.sep) or not os.path.isfile(full):
            return self.send_json({"error": "not found"}, 404)
        with open(full, "rb") as f:
            self.send_bytes(f.read(), MIME.get(os.path.splitext(full)[1], "application/octet-stream"))

    def handle_api(self, path):
        for method, rx, fn in ROUTES:
            if method != self.command and not (method == "GET" and self.command == "HEAD"):
                continue
            m = rx.match(path)
            if not m:
                continue
            con = connect()
            try:
                self._sent = False
                out = fn(self, con, *m.groups())
                con.commit()
                if not self._sent:
                    self.send_json(out if out is not None else {"ok": True})
            except ApiError as e:
                con.rollback()
                self.send_json({"error": e.message}, e.status)
            except Exception as e:  # noqa: BLE001 - ส่ง error กลับไปให้หน้าเว็บแสดง
                con.rollback()
                import traceback
                traceback.print_exc()
                self.send_json({"error": f"เกิดข้อผิดพลาดในเซิร์ฟเวอร์: {e}"}, 500)
            finally:
                con.close()
            return
        self.send_json({"error": "ไม่พบ API นี้"}, 404)

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = handle_any


def make_server(host, port):
    init_db()
    return ThreadingHTTPServer((host, port), Handler)


def main():
    global DB_PATH
    ap = argparse.ArgumentParser(description="ฐานข้อมูลจุดเก็บตัวอย่างสิ่งแวดล้อม")
    ap.add_argument("--host", default="127.0.0.1",
                    help="ใช้ 0.0.0.0 เพื่อให้เครื่องอื่นในวง LAN เข้าใช้ได้ (ค่าเริ่มต้น 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--db", default=os.environ.get("FIELDDB_PATH", DEFAULT_DB),
                    help="ตำแหน่งไฟล์ฐานข้อมูล (ค่าเริ่มต้น data/fielddata.db)")
    ap.add_argument("--no-browser", action="store_true", help="ไม่ต้องเปิดเบราว์เซอร์อัตโนมัติ")
    a = ap.parse_args()
    DB_PATH = os.path.abspath(a.db)
    srv = make_server(a.host, a.port)
    url = f"http://localhost:{a.port}/"
    print("=" * 60)
    print(" ฐานข้อมูลจุดเก็บตัวอย่าง พร้อมใช้งานแล้ว")
    print(f" เปิดเบราว์เซอร์ไปที่: {url}")
    if a.host == "0.0.0.0":
        print(f" เครื่องอื่นในวง LAN: http://<IP ของเครื่องนี้>:{a.port}/")
    print(f" ไฟล์ฐานข้อมูล: {DB_PATH}")
    print(" ปิดโปรแกรม: กด Ctrl+C หรือปิดหน้าต่างนี้")
    print("=" * 60)
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nปิดโปรแกรมแล้ว")


if __name__ == "__main__":
    main()
