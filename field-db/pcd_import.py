"""อ่าน "ตาราง คพ." — รายงานผลตรวจวิเคราะห์ตัวอย่างคุณภาพสิ่งแวดล้อมในไฟล์ Word (.docx)

รองรับ 2 รูปแบบตารางที่ใช้ในรายงาน:
  A) หนึ่งแถวต่อหนึ่งตัวอย่าง: ลำดับ | รหัสตัวอย่าง | เวลา | รายละเอียดจุดเก็บ | พารามิเตอร์... (หัวตาราง 1-2 ชั้น
     เช่น "Heavy metals (mg/l)" แล้วต่อด้วย Al, As, ...) ท้ายตารางเป็นแถว "มาตรฐาน..."
  B) หนึ่งแถวต่อหนึ่งพารามิเตอร์ (เช่น VOCs): พารามิเตอร์ | W1 | W1 (Dup) | ... | มาตรฐาน
ข้อมูลส่วนหัวเหนือตาราง: สถานที่/โครงการ, สถานการณ์, เก็บตัวอย่างวันที่ (พ.ศ.), ประเภทตัวอย่าง
ใช้แค่ Python มาตรฐาน (zipfile + xml)
"""
import io
import re
import zipfile
import xml.etree.ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
MONTHS = {
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4, "พฤษภาคม": 5, "มิถุนายน": 6,
    "กรกฎาคม": 7, "สิงหาคม": 8, "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
    "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4, "พ.ค.": 5, "มิ.ย.": 6,
    "ก.ค.": 7, "ส.ค.": 8, "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
}
MEDIA_WORDS = [  # ลำดับสำคัญ: คำที่เจาะจงกว่าก่อน
    ("ตะกอน", "sediment"), ("น้ำใต้ดิน", "groundwater"), ("น้ำบาดาล", "groundwater"),
    ("น้ำทิ้ง", "wastewater"), ("น้ำเสีย", "wastewater"), ("ระบายน้ำ", "wastewater"),
    ("น้ำผิวดิน", "surface_water"), ("แหล่งน้ำผิวดิน", "surface_water"), ("ดินผิวหน้า", "surface_soil"),
    ("อากาศ", "air"), ("ดิน", "soil"), ("น้ำ", "surface_water"),
]
HEADER_LABELS = {
    "place": "สถานที่/โครงการ/โรงงานบริษัท", "case": "สถานการณ์",
    "date": "เก็บตัวอย่างวันที่", "media": "ประเภทตัวอย่าง",
}
UNIT_MAP = {
    "mg/l": "mg/L", "µg/l": "µg/L", "ug/l": "µg/L", "μg/l": "µg/L", "mg/kg": "mg/kg",
    "ไมโครกรัมต่อลิตร": "µg/L", "มิลลิกรัมต่อลิตร": "mg/L", "มิลลิกรัมต่อกิโลกรัม": "mg/kg",
    "µs/cm": "µS/cm", "us/cm": "µS/cm", "μs/cm": "µS/cm", "ppt.": "ppt", "ppt": "ppt",
    "˚c": "°C", "°c": "°C", "oc": "°C",
}
CODE_RE = re.compile(r"^([A-Za-z]{1,5}-?\d{1,3}[A-Za-z]?)\s*(\((?:dup|duplicate)\))?$", re.I)
SKIP_VALUES = {"", "-", "–", "—", "*", "n/a", "na"}


def norm(s):
    return re.sub(r"\s+", " ", (s or "").translate(THAI_DIGITS)).strip()


def squash(s):
    return re.sub(r"[\s/]", "", s or "")


def media_of(text, default=None):
    for word, key in MEDIA_WORDS:
        if word in (text or ""):
            return key
    return default


def norm_unit(u):
    u = norm(u).strip("() ")
    return UNIT_MAP.get(u.lower().replace(" ", ""), u)


def split_param(header):
    """'DO (mg/l)' -> ('DO', 'mg/L'); 'Total Hardness (mg/l) as CaCO3' -> ('Total Hardness as CaCO3', 'mg/L')"""
    h = norm(header)
    m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*(.*)$", h)
    if not m:
        return h, ""
    name, unit, rest = m.group(1).strip(), m.group(2), m.group(3).strip()
    if not name:
        return h, ""
    return (f"{name} {rest}".strip() if rest else name), norm_unit(unit)


def unit_in(text):
    m = re.search(r"\(([^()]*)\)", norm(text))
    return norm_unit(m.group(1)) if m else ""


def parse_thai_date(text):
    """'21-23 กันยายน 2569' -> ('2026-09-21', '2026-09-23'); รองรับ ค.ศ. และ 'ต.ค. 69'"""
    t = norm(text)
    m = re.search(r"(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?\s*(" + "|".join(map(re.escape, MONTHS)) + r")\s*(\d{2,4})", t)
    if not m:
        m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
        return (m2.group(0), m2.group(0)) if m2 else (None, None)
    d1, d2, mon, year = int(m.group(1)), int(m.group(2) or m.group(1)), MONTHS[m.group(3)], int(m.group(4))
    if year < 100:
        year += 2500
    if year > 2400:
        year -= 543
    return f"{year:04d}-{mon:02d}-{d1:02d}", f"{year:04d}-{mon:02d}-{d2:02d}"


def parse_std(text):
    """ค่ามาตรฐาน -> (min, max) หรือ None: '5.0 – 9.0', '> 4', '<0.01', '35,040', '0.005'"""
    t = norm(text).replace(",", "")
    if t.lower() in SKIP_VALUES:
        return None
    m = re.match(r"^([\d.]+)\s*[–\-~]\s*([\d.]+)$", t)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.match(r"^(?:<|≤|<=|ไม่เกิน)\s*([\d.]+)", t)
    if m:
        return None, float(m.group(1))
    m = re.match(r"^(?:>|≥|>=|ไม่ต่ำกว่า)\s*([\d.]+)", t)
    if m:
        return float(m.group(1)), None
    m = re.match(r"^([\d.]+)$", t)
    if m:
        return None, float(m.group(1))
    return None


# ------------------------------------------------------------------ docx ---

def _cell_text(tc):
    paras = ["".join(t.text or "" for t in p.iter(W + "t")) for p in tc.findall(W + "p")]
    return norm(" ".join(p for p in paras if p.strip()))


def _grid(tbl):
    """ตารางเป็นตาราง 2 มิติ: ขยายเซลล์ที่รวมแนวนอน (gridSpan) และคัดลอกค่าลงในเซลล์ที่รวมแนวตั้ง (vMerge)"""
    rows = []
    for tr in tbl.findall(W + "tr"):
        row = []
        for tc in tr.findall(W + "tc"):
            pr = tc.find(W + "tcPr")
            span, cont = 1, False
            if pr is not None:
                gs = pr.find(W + "gridSpan")
                if gs is not None:
                    span = int(gs.get(W + "val", "1"))
                vm = pr.find(W + "vMerge")
                cont = vm is not None and vm.get(W + "val") != "restart"
            text = _cell_text(tc)
            for _ in range(span):
                col = len(row)
                if cont and rows and col < len(rows[-1]):
                    row.append(rows[-1][col])
                else:
                    row.append(text)
        rows.append(row)
    width = max((len(r) for r in rows), default=0)
    return [r + [""] * (width - len(r)) for r in rows]


def _blocks(raw):
    root = ET.fromstring(zipfile.ZipFile(io.BytesIO(raw)).read("word/document.xml"))
    body = root.find(W + "body")
    for el in body:
        if el.tag == W + "p":
            t = norm("".join(x.text or "" for x in el.iter(W + "t")))
            if t:
                yield "p", t
        elif el.tag == W + "tbl":
            yield "tbl", _grid(el)


def _full_width(row):
    vals = {c for c in row if c}
    return len(vals) == 1 and sum(1 for c in row if c) == len(row)


# -------------------------------------------------------------- parsing ---

class Report:
    def __init__(self):
        self.samples = {}      # key -> sample dict
        self.standards = []
        self.warnings = []
        self.skipped_tables = 0
        self.tables = 0

    def sample(self, ctx, code_cell):
        m = CODE_RE.match(norm(code_cell))
        code = m.group(1).upper() if m else norm(code_cell)
        dup = bool(m and m.group(2))
        media = ctx.get("media_key")
        key = (code + ("-DUP" if dup else ""), media, ctx.get("date_text") or "")
        s = self.samples.get(key)
        if s is None:
            d1, d2 = parse_thai_date(ctx.get("date_text", ""))
            s = self.samples[key] = {
                "key": "|".join(key), "code": code, "dup": dup,
                "sample_code": code + ("-Dup" if dup else ""),
                "media": media, "media_text": ctx.get("media_text"),
                "date": d1, "date_end": d2, "date_text": ctx.get("date_text"),
                "place": ctx.get("place"), "case": ctx.get("case"),
                "time": None, "location": None, "section": None, "appearance": None,
                "results": {}, "source": ctx.get("file"),
            }
        return s

    def add_result(self, s, param, unit, value):
        v = norm(value)
        if v.lower() in SKIP_VALUES or not param:
            return
        s["results"].setdefault(param, {"parameter": param, "value_text": v, "unit": unit})

    def add_std(self, ctx, label, param, unit, text, refs):
        lim = parse_std(text)
        if not lim:
            return
        media = media_of(label.replace("มาตรฐาน", ""), ctx.get("media_key"))
        mark = re.search(r"\((\d)\)|(\*)", label)
        ref = re.sub(r"\(\d\)|\*", "", label).strip()
        if mark:
            note = refs.get(mark.group(1) or "*")
            if note:
                ref = note
        self.standards.append({"media": media, "parameter": param, "min": lim[0], "max": lim[1],
                               "unit": unit, "reference": ref[:300], "label": label})


def _parse_footnotes(paras):
    refs = {}
    good = lambda x: x.startswith(("ประกาศ", "มาตรฐาน")) or "เรื่อง" in x
    for t in paras:
        m = re.match(r"^\((\d)\)\s*(.+)$", t)
        # บางไฟล์มีบรรทัดที่ขึ้นบรรทัดใหม่แล้วดันขึ้นต้นด้วย "(2)" ด้วย -> เลือกบรรทัดที่เป็นชื่อประกาศจริง
        if m and (m.group(1) not in refs or (good(m.group(2)) and not good(refs[m.group(1)]))):
            refs[m.group(1)] = m.group(2)
        m = re.match(r"^(?:หมายเหตุ\s*:\s*)?\*\s*(ประกาศ.+)$", t)
        if m:
            refs.setdefault("*", m.group(1))
    return refs


def _table_layout_a(rep, ctx, g, refs):
    hdr_pos = None
    for r in range(min(3, len(g))):
        for c, v in enumerate(g[r]):
            if squash(v) == "รหัสตัวอย่าง":
                hdr_pos = (r, c)
                break
        if hdr_pos:
            break
    r0, code_col = hdr_pos
    end = r0
    while end < len(g) and squash(g[end][code_col]) == "รหัสตัวอย่าง":
        end += 1
    header = g[r0:end]
    cols = {}
    for c in range(len(g[0])):
        labels = []
        for row in header:
            if row[c] and (not labels or labels[-1] != row[c]):
                labels.append(row[c])
        if not labels:
            continue
        top = squash(labels[0])
        if top in ("ลำดับ", "ที่"):
            cols[c] = ("seq",)
        elif top == "รหัสตัวอย่าง":
            cols[c] = ("code",)
        elif top == "เวลา":
            cols[c] = ("time",)
        elif top.startswith("รายละเอียด") or top.startswith("จุดเก็บ") or "จุดเก็บตัวอย่าง" in top:
            cols[c] = ("location",)
        elif top.startswith("ลักษณะ"):
            cols[c] = ("appearance",)
        else:
            name, unit = split_param(labels[-1])
            if not unit and len(labels) > 1:
                unit = unit_in(labels[0])
            cols[c] = ("param", name, unit)
    section = None
    for row in g[end:]:
        if _full_width(row):
            section = row[0]
            continue
        first = next((v for v in row if v), "")
        if first.startswith("มาตรฐาน"):
            for c, spec in cols.items():
                if spec[0] == "param":
                    rep.add_std(ctx, first, spec[1], spec[2], row[c], refs)
            continue
        code = row[code_col]
        if not code or not CODE_RE.match(code):
            if code:
                rep.warnings.append(f"ข้ามแถวที่อ่านรหัสตัวอย่างไม่ได้: {code[:40]}")
            continue
        s = rep.sample(ctx, code)
        if section and not s["section"]:
            s["section"] = section
        for c, spec in cols.items():
            v = row[c]
            if spec[0] == "param":
                rep.add_result(s, spec[1], spec[2], v)
            elif spec[0] in ("time", "location", "appearance") and v and not s[spec[0]]:
                s[spec[0]] = v


def _table_layout_b(rep, ctx, g, refs):
    best, hr = 0, None
    for r in range(min(4, len(g))):
        n = sum(1 for v in g[r] if CODE_RE.match(v))
        if n > best:
            best, hr = n, r
    sample_cols = [c for c, v in enumerate(g[hr]) if CODE_RE.match(v)]
    first, last = sample_cols[0], sample_cols[-1]
    param_col = first - 1
    std_col = None
    for c in range(last + 1, len(g[0])):
        if any("มาตรฐาน" in g[r][c] for r in range(hr + 1)):
            std_col = c
            break
    unit = ""
    for r in range(hr):
        for c in sample_cols:
            unit = unit or unit_in(g[r][c])
    std_label = g[0][std_col] if std_col is not None else ""
    for row in g[hr + 1:]:
        if _full_width(row):
            unit = unit_in(row[0]) or unit
            continue
        name, own_unit = split_param(row[param_col])
        if not name or name.isdigit():
            continue
        for c in sample_cols:
            s = rep.sample(ctx, g[hr][c])
            rep.add_result(s, name, own_unit or unit, row[c])
        if std_col is not None:
            rep.add_std(ctx, std_label, name, own_unit or unit, row[std_col], refs)


def parse_docx(raw, filename="", rep=None):
    rep = rep or Report()
    try:
        blocks = list(_blocks(raw))
    except (KeyError, zipfile.BadZipFile, ET.ParseError) as e:
        rep.warnings.append(f"{filename}: เปิดไฟล์ Word ไม่ได้ ({e})")
        return rep
    ctx = {"file": filename}
    for i, (kind, val) in enumerate(blocks):
        if kind == "p":
            for key, label in HEADER_LABELS.items():
                if squash(val).startswith(squash(label)):
                    # ตัดป้ายออกโดยนับตัวอักษรที่ไม่ใช่ช่องว่าง (ป้ายในไฟล์อาจเว้นวรรคต่างกัน)
                    want, j = len(squash(label)), 0
                    while want and j < len(val):
                        if not val[j].isspace() and val[j] != "/":
                            want -= 1
                        j += 1
                    ctx[{"place": "place", "case": "case", "date": "date_text", "media": "media_text"}[key]] = val[j:].strip(" :")
            if ctx.get("media_text"):
                ctx["media_key"] = media_of(ctx["media_text"], "other")
            continue
        g = val
        rep.tables += 1
        if not g or not g[0]:
            continue
        # คำอธิบายที่ตามหลังตาราง (หมายเหตุ / (1) ประกาศ...) ใช้เป็นแหล่งอ้างอิงค่ามาตรฐาน
        after = []   # ข้ามตารางที่ติดกันไปได้ จนถึงหัวเรื่องถัดไป
        for kind2, v2 in blocks[i + 1:]:
            if kind2 == "p" and v2.startswith("ผลตรวจ"):
                break
            if kind2 == "p":
                after.append(v2)
        refs = _parse_footnotes(after)
        head = [squash(v) for r in g[:3] for v in r]
        try:
            if "รหัสตัวอย่าง" in head:
                _table_layout_a(rep, ctx, g, refs)
            elif any(CODE_RE.match(v) for r in g[:4] for v in r):
                _table_layout_b(rep, ctx, g, refs)
            else:
                rep.skipped_tables += 1
        except (IndexError, KeyError, TypeError) as e:
            rep.skipped_tables += 1
            rep.warnings.append(f"{filename}: อ่านตารางที่ {rep.tables} ไม่ได้ ({e})")
    return rep


def report_json(rep):
    samples = []
    for s in rep.samples.values():
        d = dict(s)
        d["results"] = list(s["results"].values())
        samples.append(d)
    order = {"surface_water": 0, "groundwater": 1, "sediment": 2, "soil": 3, "surface_soil": 4}

    def sort_key(s):
        m = re.match(r"([A-Za-z]+)-?(\d+)", s["code"])
        return (order.get(s["media"], 9), m.group(1) if m else s["code"], int(m.group(2)) if m else 0, s["dup"])
    samples.sort(key=sort_key)
    # หน่วยไม่ตรงกันของพารามิเตอร์เดียวกัน (เช่น VOCs ตารางหนึ่งเขียน µg/l อีกตารางเขียน mg/l) -> เตือนรวมเป็นก้อน
    units = {}
    for smp in samples:
        for r in smp["results"]:
            units.setdefault((smp["media"], r["parameter"]), {}).setdefault(r["unit"] or "", []).append(smp["sample_code"])
    groups = {}
    for (media, param), by_unit in units.items():
        if len(by_unit) < 2:
            continue
        major = max(by_unit, key=lambda u: len(by_unit[u]))
        odd = sorted({c for u, cs in by_unit.items() if u != major for c in cs})
        g = groups.setdefault((media, tuple(sorted(by_unit))), {"params": [], "samples": set(), "major": major})
        g["params"].append(param)
        g["samples"].update(odd)
    for (media, us), g in groups.items():
        rep.warnings.append(
            f"หน่วยไม่ตรงกัน ({' / '.join(u or 'ไม่มีหน่วย' for u in us)}) ใน {len(g['params'])} พารามิเตอร์ "
            f"เช่น {', '.join(g['params'][:3])} — ตัวอย่าง {', '.join(sorted(g['samples']))} ใช้หน่วยต่างจากส่วนใหญ่ "
            f"({g['major'] or 'ไม่มีหน่วย'}) โปรดตรวจต้นฉบับ: ระบบเทียบค่ามาตรฐานด้วยตัวเลขโดยไม่แปลงหน่วย")
    # ค่ามาตรฐานซ้ำ (ประเภท+พารามิเตอร์เดียวกัน) เก็บตัวแรกไว้ใช้ ตัวที่เหลือแจ้งว่าเป็นทางเลือก
    seen, stds = set(), []
    for st in rep.standards:
        k = (st["media"], st["parameter"].lower())
        st = dict(st, primary=k not in seen)
        seen.add(k)
        if not any(x["media"] == st["media"] and x["parameter"] == st["parameter"] and x["min"] == st["min"]
                   and x["max"] == st["max"] for x in stds):
            stds.append(st)
    return {"samples": samples, "standards": stds, "warnings": rep.warnings,
            "tables": rep.tables, "skipped_tables": rep.skipped_tables}
