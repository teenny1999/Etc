#!/usr/bin/env python3
"""
GUI (desktop window) for counting buildings within a radius of a coordinate
using Microsoft's GlobalMLBuildingFootprints dataset, with a preview map
built from OpenStreetMap tiles.

Reuses the download/scan logic in count_buildings_msft.py unchanged - this
file only adds the window, the map preview, and background-thread wiring
so the UI never freezes while a tile downloads or a dataset file is scanned.

Requires: Pillow (PIL) for the map image; tkinter (bundled with the
standard Windows/macOS Python installer; on Debian/Ubuntu Linux install
the `python3-tk` package separately).

Usage:
    python count_buildings_msft_gui.py
"""

import math
import os
import queue
import sys
import threading
import tkinter as tk
import urllib.error
import urllib.request
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

from count_buildings_msft import (
    DEFAULT_CACHE_DIR,
    DEFAULT_DATASET_LINKS_URL,
    DEFAULT_RADIUS_M,
    HRS_RING_LABELS_TH,
    run_combined,
)

DEFAULT_PEOPLE_PER_BUILDING = 3.0

TILE_SIZE = 256
MAP_PX = 480
MAP_PADDING = 1.4  # show a bit more than the raw radius so the circle isn't edge-to-edge
MAX_ZOOM = 18
MIN_ZOOM = 2
TILE_SERVER = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_USER_AGENT = "count-buildings-msft-gui/1.0 (local desktop tool, not for bulk use)"


def meters_per_pixel(lat: float, zoom: int) -> float:
    return 156543.03392 * math.cos(math.radians(lat)) / (2**zoom)


def lonlat_to_pixel(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    lat_rad = math.radians(lat)
    n = 2**zoom
    x = (lon + 180.0) / 360.0 * n * TILE_SIZE
    y = (
        (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi)
        / 2.0
        * n
        * TILE_SIZE
    )
    return x, y


def choose_zoom(lat: float, radius_m: float, image_px: int) -> int:
    desired_mpp = (2 * radius_m * MAP_PADDING) / image_px
    for zoom in range(MAX_ZOOM, MIN_ZOOM - 1, -1):
        if meters_per_pixel(lat, zoom) >= desired_mpp:
            return zoom
    return MIN_ZOOM


def fetch_tile(zoom: int, x: int, y: int, cache_dir: str) -> Image.Image | None:
    n = 2**zoom
    if not (0 <= y < n):
        return None
    x = x % n  # wrap around the antimeridian instead of failing
    tile_cache_dir = os.path.join(cache_dir, "map_tiles")
    os.makedirs(tile_cache_dir, exist_ok=True)
    tile_path = os.path.join(tile_cache_dir, f"{zoom}_{x}_{y}.png")
    if not os.path.exists(tile_path):
        url = TILE_SERVER.format(z=zoom, x=x, y=y)
        request = urllib.request.Request(url, headers={"User-Agent": TILE_USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = response.read()
            tmp_path = tile_path + ".part"
            with open(tmp_path, "wb") as f:
                f.write(data)
            os.replace(tmp_path, tile_path)
        except (urllib.error.URLError, urllib.error.HTTPError):
            return None
    try:
        return Image.open(tile_path).convert("RGBA")
    except OSError:
        return None


def build_map_image(lat: float, lon: float, radius_m: float, cache_dir: str) -> Image.Image:
    """Stitches OpenStreetMap tiles into a MAP_PX x MAP_PX preview centered
    on (lat, lon), with a marker and a circle showing the search radius."""
    zoom = choose_zoom(lat, radius_m, MAP_PX)
    center_x, center_y = lonlat_to_pixel(lat, lon, zoom)
    box_left = center_x - MAP_PX / 2
    box_top = center_y - MAP_PX / 2

    composite = Image.new("RGBA", (MAP_PX, MAP_PX), (222, 222, 222, 255))
    tile_x_min = int(box_left // TILE_SIZE)
    tile_x_max = int((box_left + MAP_PX) // TILE_SIZE)
    tile_y_min = int(box_top // TILE_SIZE)
    tile_y_max = int((box_top + MAP_PX) // TILE_SIZE)

    for tx in range(tile_x_min, tile_x_max + 1):
        for ty in range(tile_y_min, tile_y_max + 1):
            tile = fetch_tile(zoom, tx, ty, cache_dir)
            if tile is None:
                continue
            paste_x = int(tx * TILE_SIZE - box_left)
            paste_y = int(ty * TILE_SIZE - box_top)
            composite.alpha_composite(tile, (paste_x, paste_y))

    draw = ImageDraw.Draw(composite)
    cx, cy = MAP_PX / 2, MAP_PX / 2
    radius_px = radius_m / meters_per_pixel(lat, zoom)
    draw.ellipse(
        [cx - radius_px, cy - radius_px, cx + radius_px, cy + radius_px],
        outline=(214, 39, 40, 230),
        width=3,
    )
    marker_r = 6
    draw.ellipse(
        [cx - marker_r, cy - marker_r, cx + marker_r, cy + marker_r],
        fill=(214, 39, 40, 255),
        outline=(255, 255, 255, 255),
        width=2,
    )

    attribution = "© OpenStreetMap contributors"
    text_bbox = draw.textbbox((0, 0), attribution)
    text_w = text_bbox[2] - text_bbox[0]
    text_h = text_bbox[3] - text_bbox[1]
    pad = 4
    draw.rectangle(
        [0, MAP_PX - text_h - 2 * pad, text_w + 2 * pad, MAP_PX],
        fill=(255, 255, 255, 180),
    )
    draw.text((pad, MAP_PX - text_h - pad), attribution, fill=(0, 0, 0, 255))

    return composite.convert("RGB")


class QueueWriter:
    """Redirect target for sys.stdout/sys.stderr: pushes text into a queue
    the Tk main loop drains, since Tk widgets can't be touched off-thread."""

    def __init__(self, q: "queue.Queue[str]"):
        self.q = q

    def write(self, text: str) -> None:
        if text:
            self.q.put(text)

    def flush(self) -> None:
        pass


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("นับอาคารจาก Microsoft GlobalMLBuildingFootprints")
        root.geometry("900x780")
        root.minsize(800, 680)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.map_queue: "queue.Queue[object]" = queue.Queue()
        self.worker_thread: threading.Thread | None = None

        self._build_widgets()
        self.root.after(80, self._drain_queues)

    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 6}

        form = ttk.Frame(self.root)
        form.pack(side="top", fill="x", **pad)

        ttk.Label(form, text="ละติจูด (lat):").grid(row=0, column=0, sticky="w")
        self.lat_var = tk.StringVar(value="13.7563")
        lat_entry = ttk.Entry(form, textvariable=self.lat_var, width=16)
        lat_entry.grid(row=0, column=1, padx=(4, 16))
        self._install_context_menu(lat_entry, editable=True)

        ttk.Label(form, text="ลองจิจูด (lon):").grid(row=0, column=2, sticky="w")
        self.lon_var = tk.StringVar(value="100.5018")
        lon_entry = ttk.Entry(form, textvariable=self.lon_var, width=16)
        lon_entry.grid(row=0, column=3, padx=(4, 16))
        self._install_context_menu(lon_entry, editable=True)

        ttk.Label(form, text="รัศมี (เมตร):").grid(row=0, column=4, sticky="w")
        self.radius_var = tk.StringVar(value=str(DEFAULT_RADIUS_M))
        radius_entry = ttk.Entry(form, textvariable=self.radius_var, width=10)
        radius_entry.grid(row=0, column=5, padx=(4, 16))
        self._install_context_menu(radius_entry, editable=True)

        self.run_button = ttk.Button(form, text="ค้นหา", command=self.on_search)
        self.run_button.grid(row=0, column=6, padx=(0, 4))

        ttk.Label(form, text="คนต่อหลัง (ประมาณการ, สำหรับ HRS):").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(6, 0)
        )
        self.people_per_building_var = tk.StringVar(value=str(DEFAULT_PEOPLE_PER_BUILDING))
        ppb_entry = ttk.Entry(form, textvariable=self.people_per_building_var, width=10)
        ppb_entry.grid(row=1, column=3, sticky="w", padx=(4, 0), pady=(6, 0))
        self._install_context_menu(ppb_entry, editable=True)

        self.status_var = tk.StringVar(value="กรอกพิกัดแล้วกด “ค้นหา”")
        ttk.Label(self.root, textvariable=self.status_var, foreground="#555").pack(
            side="top", anchor="w", padx=8
        )

        body = ttk.Frame(self.root)
        body.pack(side="top", fill="both", expand=True, padx=8, pady=(4, 8))

        map_frame = ttk.LabelFrame(body, text="แผนที่ (OpenStreetMap)")
        map_frame.pack(side="left", fill="both", padx=(0, 8))
        self.map_label = ttk.Label(map_frame)
        self.map_label.pack(padx=4, pady=4)
        self._placeholder_image = ImageTk.PhotoImage(
            Image.new("RGB", (MAP_PX, MAP_PX), (230, 230, 230))
        )
        self.map_label.configure(image=self._placeholder_image)

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)

        result_frame = ttk.LabelFrame(right, text="ผลลัพธ์ (เลือก/คัดลอกได้)")
        result_frame.pack(side="top", fill="x")
        self.result_var = tk.StringVar(value="-")
        result_entry = tk.Entry(
            result_frame,
            textvariable=self.result_var,
            font=("TkDefaultFont", 20, "bold"),
            state="readonly",
            relief="flat",
            borderwidth=0,
        )
        result_entry.pack(anchor="w", fill="x", padx=8, pady=(6, 0))
        self._install_context_menu(result_entry, editable=False)

        self.result_meta_var = tk.StringVar(value="")
        meta_entry = tk.Entry(
            result_frame,
            textvariable=self.result_meta_var,
            foreground="#555",
            state="readonly",
            relief="flat",
            borderwidth=0,
        )
        meta_entry.pack(anchor="w", fill="x", padx=8, pady=(0, 6))
        self._install_context_menu(meta_entry, editable=False)

        hrs_frame = ttk.LabelFrame(
            right, text="ประชากรตามวงรัศมี สำหรับ HRS (Table 5-9) — เลือก/คัดลอกได้"
        )
        hrs_frame.pack(side="top", fill="x", pady=(8, 0))
        ttk.Label(hrs_frame, text="วงรัศมี", foreground="#555").grid(
            row=0, column=0, sticky="w", padx=(8, 4), pady=(4, 2)
        )
        ttk.Label(hrs_frame, text="จำนวนอาคาร", foreground="#555").grid(
            row=0, column=1, sticky="w", padx=4, pady=(4, 2)
        )
        ttk.Label(hrs_frame, text="ประชากรประมาณการ", foreground="#555").grid(
            row=0, column=2, sticky="w", padx=4, pady=(4, 2)
        )
        self.hrs_building_vars: list[tk.StringVar] = []
        self.hrs_population_vars: list[tk.StringVar] = []
        for i, ring_label in enumerate(HRS_RING_LABELS_TH):
            ttk.Label(hrs_frame, text=ring_label).grid(
                row=i + 1, column=0, sticky="w", padx=(8, 4), pady=1
            )
            building_var = tk.StringVar(value="-")
            building_entry = tk.Entry(
                hrs_frame,
                textvariable=building_var,
                state="readonly",
                relief="flat",
                borderwidth=0,
                width=10,
            )
            building_entry.grid(row=i + 1, column=1, sticky="w", padx=4, pady=1)
            self._install_context_menu(building_entry, editable=False)
            self.hrs_building_vars.append(building_var)

            population_var = tk.StringVar(value="-")
            population_entry = tk.Entry(
                hrs_frame,
                textvariable=population_var,
                state="readonly",
                relief="flat",
                borderwidth=0,
                width=10,
                font=("TkDefaultFont", 10, "bold"),
            )
            population_entry.grid(row=i + 1, column=2, sticky="w", padx=4, pady=(1, 4))
            self._install_context_menu(population_entry, editable=False)
            self.hrs_population_vars.append(population_var)

        log_frame = ttk.LabelFrame(right, text="สถานะการทำงาน (เลือก/คัดลอกได้)")
        log_frame.pack(side="top", fill="both", expand=True, pady=(8, 0))
        self.log_text = tk.Text(log_frame, height=14, wrap="word", undo=False)
        self.log_text.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4)
        log_scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        log_scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=log_scroll.set)
        # Keep the log selectable and copyable, but block typing/pasting
        # into it so it still behaves like read-only output.
        self.log_text.bind("<Key>", self._block_text_edit)
        self.log_text.bind("<<Paste>>", lambda e: "break")
        self._install_context_menu(self.log_text, editable=False)

    @staticmethod
    def _block_text_edit(event: tk.Event) -> str | None:
        ctrl_or_cmd = bool(event.state & 0x4)
        if ctrl_or_cmd and event.keysym.lower() in ("c", "a"):
            return None  # allow copy and select-all
        if event.keysym in (
            "Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next",
            "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
        ):
            return None  # allow navigation/selection
        return "break"  # block everything else that would edit the text

    def _install_context_menu(self, widget: tk.Widget, editable: bool) -> None:
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(label="คัดลอก (Copy)", command=lambda: self._copy_from(widget))
        if editable:
            menu.add_command(label="วาง (Paste)", command=lambda: widget.event_generate("<<Paste>>"))
            menu.add_command(label="ตัด (Cut)", command=lambda: widget.event_generate("<<Cut>>"))
        menu.add_command(label="เลือกทั้งหมด (Select All)", command=lambda: self._select_all(widget))

        def show_menu(event: tk.Event) -> None:
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        widget.bind("<Button-3>", show_menu)

    def _copy_from(self, widget: tk.Widget) -> None:
        try:
            if isinstance(widget, tk.Text):
                text = widget.get("sel.first", "sel.last")
            else:
                text = widget.selection_get()
        except tk.TclError:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    @staticmethod
    def _select_all(widget: tk.Widget) -> None:
        if isinstance(widget, tk.Text):
            widget.tag_add("sel", "1.0", "end")
        elif isinstance(widget, (tk.Entry, ttk.Entry)):
            widget.selection_range(0, "end")

    def _append_log(self, text: str) -> None:
        # Progress lines from count_buildings_msft use \r to overwrite the
        # current line like a terminal would; a Text widget doesn't do that
        # on its own, so emulate it by erasing back to the line start.
        for i, part in enumerate(text.split("\r")):
            if i > 0:
                self.log_text.delete("end-1c linestart", "end-1c")
            if part:
                self.log_text.insert("end", part)
        self.log_text.see("end")

    def _validated_inputs(self) -> tuple[float, float, int, float] | None:
        try:
            lat = float(self.lat_var.get().strip())
            if not (-90 <= lat <= 90):
                raise ValueError("lat out of range")
        except ValueError:
            self.status_var.set("ละติจูดต้องเป็นตัวเลขระหว่าง -90 ถึง 90")
            return None
        try:
            lon = float(self.lon_var.get().strip())
            if not (-180 <= lon <= 180):
                raise ValueError("lon out of range")
        except ValueError:
            self.status_var.set("ลองจิจูดต้องเป็นตัวเลขระหว่าง -180 ถึง 180")
            return None
        try:
            radius = int(self.radius_var.get().strip())
            if radius <= 0:
                raise ValueError("radius must be positive")
        except ValueError:
            self.status_var.set("รัศมีต้องเป็นจำนวนเต็มมากกว่า 0")
            return None
        try:
            people_per_building = float(self.people_per_building_var.get().strip())
            if people_per_building < 0:
                raise ValueError("must be non-negative")
        except ValueError:
            self.status_var.set("คนต่อหลังต้องเป็นตัวเลขมากกว่าหรือเท่ากับ 0")
            return None
        return lat, lon, radius, people_per_building

    def on_search(self) -> None:
        if self.worker_thread is not None and self.worker_thread.is_alive():
            return
        inputs = self._validated_inputs()
        if inputs is None:
            return
        lat, lon, radius, people_per_building = inputs

        self.run_button.configure(state="disabled")
        self.status_var.set("กำลังค้นหา...")
        self.result_var.set("-")
        self.result_meta_var.set("")
        for var in self.hrs_building_vars:
            var.set("-")
        for var in self.hrs_population_vars:
            var.set("-")
        self.log_text.delete("1.0", "end")

        self.worker_thread = threading.Thread(
            target=self._worker, args=(lat, lon, radius, people_per_building), daemon=True
        )
        self.worker_thread.start()

    def _worker(
        self, lat: float, lon: float, radius: int, people_per_building: float
    ) -> None:
        try:
            map_image = build_map_image(lat, lon, radius, DEFAULT_CACHE_DIR)
            self.map_queue.put(("map", map_image))
        except Exception as exc:  # noqa: BLE001 - surface it, don't crash the thread
            self.log_queue.put(f"[แผนที่] โหลดแผนที่ไม่สำเร็จ: {exc}\n")

        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = QueueWriter(self.log_queue)
        try:
            total, ring_counts = run_combined(
                lat, lon, radius, DEFAULT_CACHE_DIR, DEFAULT_DATASET_LINKS_URL
            )
            self.map_queue.put(
                ("done", (total, ring_counts, lat, lon, radius, people_per_building))
            )
        except Exception as exc:  # noqa: BLE001 - report it in the UI, don't crash the thread
            self.map_queue.put(("error", str(exc)))
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

    def _drain_queues(self) -> None:
        try:
            while True:
                text = self.log_queue.get_nowait()
                self._append_log(text)
        except queue.Empty:
            pass

        try:
            while True:
                kind, payload = self.map_queue.get_nowait()
                if kind == "map":
                    photo = ImageTk.PhotoImage(payload)
                    self.map_label.configure(image=photo)
                    self.map_label.image = photo  # keep a reference alive
                elif kind == "done":
                    total, ring_counts, lat, lon, radius, people_per_building = payload
                    self.result_var.set(f"{total:,} อาคาร")
                    self.result_meta_var.set(
                        f"รัศมี {radius:,} ม. รอบ ({lat}, {lon})"
                    )
                    for i, count in enumerate(ring_counts):
                        self.hrs_building_vars[i].set(f"{count:,}")
                        population = round(count * people_per_building)
                        self.hrs_population_vars[i].set(f"{population:,}")
                    self.status_var.set("เสร็จสิ้น")
                    self.run_button.configure(state="normal")
                elif kind == "error":
                    self.status_var.set(f"เกิดข้อผิดพลาด: {payload}")
                    self.run_button.configure(state="normal")
        except queue.Empty:
            pass

        self.root.after(80, self._drain_queues)


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
