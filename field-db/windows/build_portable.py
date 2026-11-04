#!/usr/bin/env python3
"""สร้างชุดโปรแกรมแบบพกพาสำหรับ Windows (ไม่ต้องติดตั้ง Python / ไม่ต้องใช้สิทธิ์ admin)

    python field-db/windows/build_portable.py            # ดาวน์โหลด Python แบบ embeddable จาก python.org
    python field-db/windows/build_portable.py --python-zip python-3.12.10-embed-amd64.zip

ผลลัพธ์: dist/FieldDB-windows.zip  (แตกไฟล์แล้วดับเบิลคลิก Start-FieldDB.bat)

ใช้ Python ตัวทางการจาก python.org (python.exe มีลายเซ็นดิจิทัลของ Python Software Foundation)
และตรวจ SHA-256 กับค่าที่ python.org ประกาศไว้ในไฟล์ .spdx.json ของรุ่นนี้
"""
import argparse
import hashlib
import io
import os
import shutil
import sys
import urllib.request
import zipfile

for _s in (sys.stdout, sys.stderr):  # คอนโซล Windows (cp1252) พิมพ์ภาษาไทยไม่ได้ -> อย่าให้ล้ม
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

PY_VERSION = "3.12.10"
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
PY_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
PTH = "python312._pth"

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)              # field-db/
APP_FILES = ["app.py", "pcd_import.py", "seed_demo.py", "README.md"]


def bat(lines):
    """ไฟล์ .bat ต้องเป็น CRLF และ ASCII ล้วน (ข้อความภาษาไทยให้ Python เป็นคนพิมพ์)"""
    text = "\r\n".join(lines) + "\r\n"
    text.encode("ascii")
    return text.encode("ascii")


PRELUDE = [
    "@echo off",
    "setlocal",
    'cd /d "%~dp0"',
    "set PYTHONUTF8=1",
    "set PYTHONIOENCODING=utf-8",
    "chcp 65001 >nul",
]
BATS = {
    "Start-FieldDB.bat": PRELUDE + [
        '"%~dp0python\\python.exe" "%~dp0app\\app.py" %*',
        "if errorlevel 1 pause",
    ],
    "Start-Demo-Data.bat": PRELUDE + [
        "rem Try the program with sample (fake) data in a separate database file.",
        'if not exist "%~dp0app\\data\\demo.db" "%~dp0python\\python.exe" "%~dp0app\\seed_demo.py" "%~dp0app\\data\\demo.db"',
        '"%~dp0python\\python.exe" "%~dp0app\\app.py" --db "%~dp0app\\data\\demo.db" --port 8766 %*',
        "if errorlevel 1 pause",
    ],
    "Start-Shared-LAN.bat": PRELUDE + [
        "rem Let other computers on the same network open this program.",
        "rem Windows Firewall may ask for permission the first time.",
        '"%~dp0python\\python.exe" "%~dp0app\\app.py" --host 0.0.0.0 %*',
        "if errorlevel 1 pause",
    ],
}

README_TH = """ฐานข้อมูลจุดเก็บตัวอย่าง — ชุดสำหรับ Windows (ไม่ต้องติดตั้ง)
=================================================================

วิธีใช้
  1) แตกไฟล์ zip ทั้งโฟลเดอร์ไปไว้ที่ Documents หรือ Desktop
     (อย่าเปิดจากในไฟล์ zip โดยตรง และไม่ควรวางใน C:\\Program Files เพราะเขียนไฟล์ไม่ได้)
  2) ดับเบิลคลิก  Start-FieldDB.bat
     เบราว์เซอร์จะเปิดหน้าโปรแกรมให้เอง (http://localhost:8765/)
  3) ระหว่างใช้งานอย่าปิดหน้าต่างดำ (console) — ปิดหน้าต่างนั้นเมื่อเลิกใช้

ไฟล์อื่น
  Start-Demo-Data.bat   ลองเล่นกับข้อมูลสมมติ (แยกไฟล์ฐานข้อมูล ไม่ปนกับข้อมูลจริง) ที่ http://localhost:8766/
  Start-Shared-LAN.bat  ให้เครื่องอื่นในวง LAN/Wi-Fi เดียวกันเปิดใช้ได้ที่ http://<IP เครื่องนี้>:8765/
                        (ครั้งแรก Windows Firewall อาจถามสิทธิ์ — ยังไม่มีระบบรหัสผ่าน ใช้ในเครือข่ายที่ไว้ใจเท่านั้น)

ข้อมูลอยู่ที่ไหน
  app\\data\\fielddata.db   ข้อมูลทั้งหมด (รวมรูปถ่าย) อยู่ในไฟล์นี้ไฟล์เดียว
  สำรองข้อมูล: ในโปรแกรมเมนู "ส่งออก" -> "สำรองฐานข้อมูลทั้งไฟล์" หรือคัดลอกไฟล์นี้ตอนปิดโปรแกรม
  อัปเดตโปรแกรมเวอร์ชันใหม่: แตกไฟล์ชุดใหม่ แล้วคัดลอกโฟลเดอร์ app\\data จากชุดเดิมไปทับ

ถ้าเปิดไม่ได้
  - Windows ขึ้น "Windows protected your PC": กด More info -> Run anyway
    (ไฟล์ .bat ไม่มีลายเซ็นดิจิทัล — python.exe ข้างในเป็นตัวทางการจาก python.org)
  - เครื่องที่ทำงานบล็อกการรันโปรแกรม: ต้องให้ฝ่าย IT อนุญาตโฟลเดอร์นี้
  - ต้องต่ออินเทอร์เน็ตเพื่อโหลดภาพแผนที่ดาวเทียม (ข้อมูลของคุณอยู่ในเครื่องเท่านั้น)
  - ใช้ได้กับ Windows 10/11 แบบ 64-bit
"""


def get_python_zip(path):
    if path:
        data = open(path, "rb").read()
    else:
        print(f"ดาวน์โหลด {PY_URL}")
        with urllib.request.urlopen(PY_URL, timeout=120) as r:
            data = r.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != PY_SHA256:
        sys.exit(f"SHA-256 ไม่ตรง: {digest} (ต้องเป็น {PY_SHA256}) — ไม่ใช้ไฟล์นี้")
    return data


def build(out_dir, python_zip=None):
    stage = os.path.join(out_dir, "FieldDB")
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(os.path.join(stage, "python"))
    with zipfile.ZipFile(io.BytesIO(get_python_zip(python_zip))) as z:
        z.extractall(os.path.join(stage, "python"))
    # ให้ Python แบบพกพาเห็นโฟลเดอร์ app (สำหรับ seed_demo.py ที่ import app)
    with open(os.path.join(stage, "python", PTH), "w", newline="\r\n") as f:
        f.write("python312.zip\n.\n..\\app\n")

    app_dir = os.path.join(stage, "app")
    os.makedirs(app_dir)
    for name in APP_FILES:
        shutil.copy2(os.path.join(SRC, name), app_dir)
    shutil.copytree(os.path.join(SRC, "static"), os.path.join(app_dir, "static"))
    for name, lines in BATS.items():
        with open(os.path.join(stage, name), "wb") as f:
            f.write(bat(lines))
    with open(os.path.join(stage, "README-Windows.txt"), "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(README_TH)

    zpath = os.path.join(out_dir, "FieldDB-windows.zip")
    if os.path.exists(zpath):
        os.remove(zpath)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root, _, files in os.walk(stage):
            for fn in sorted(files):
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, out_dir))
    print(f"สร้างแล้ว: {zpath} ({os.path.getsize(zpath) / 1e6:.1f} MB)")
    return zpath


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    ap.add_argument("--python-zip", help="ใช้ไฟล์ embeddable zip ที่ดาวน์โหลดไว้แล้ว (ยังตรวจ SHA-256 เหมือนเดิม)")
    a = ap.parse_args()
    build(os.path.abspath(a.out), a.python_zip)
