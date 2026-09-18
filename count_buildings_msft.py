#!/usr/bin/env python3
"""
Count buildings within a radius around a coordinate using Microsoft's
Global ML Building Footprints dataset.
https://github.com/microsoft/GlobalMLBuildingFootprints

The dataset is partitioned into gzipped line-delimited GeoJSON files, one
per country x zoom-9 Bing quadkey tile (each tile covers roughly 50-100 km
on a side). This script:
  1. Downloads dataset-links.csv (the tile -> URL index).
  2. Works out which tile(s) the search circle touches.
  3. Streams and decompresses each matching tile, testing every building's
     centroid against the radius (haversine distance), without ever
     holding a whole tile in memory.

A tile can be tens to hundreds of MB, so this can take a while and uses
real bandwidth - results and downloaded tiles are cached under
--cache-dir (default: ./.msft_buildings_cache) so re-running for the same
tile is instant.

Usage:
    python count_buildings_msft.py <lat> <lon> [--radius METERS] [--cache-dir DIR]

Example:
    python count_buildings_msft.py 13.7563 100.5018 --radius 2000
"""

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_DATASET_LINKS_URL = (
    "https://bfppub.blob.core.windows.net/%24web/2026-08-13/dataset-links.csv"
)
DEFAULT_RADIUS_M = 2000
DEFAULT_CACHE_DIR = ".msft_buildings_cache"
ZOOM = 9  # tile zoom level used by the dataset's quadkey partitioning

# HRS Rule Table 5-9 "Distance-Weighted Nearby Population" bands (upper bound
# of each ring, in meters; rings are mutually exclusive, e.g. band 2 is
# (200, 400]). The HRS scoring page applies the x1/x0.5/x0.25/... weights
# itself - this script only needs to report the raw count per band.
HRS_RING_BOUNDS_M = (200, 400, 800, 1600, 3200, 6400)
HRS_RING_LABELS_TH = (
    "0-200 ม.",
    "200-400 ม.",
    "400-800 ม.",
    "800-1600 ม.",
    "1600-3200 ม.",
    "3200-6400 ม.",
)
EARTH_RADIUS_M = 6371000.0
HTTP_TIMEOUT_S = 60
DOWNLOAD_CHUNK = 1024 * 1024


def deg2tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    lat_rad = math.radians(lat)
    n = 2**zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int(
        (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi)
        / 2.0
        * n
    )
    return max(0, min(n - 1, xtile)), max(0, min(n - 1, ytile))


def tile_to_quadkey(x: int, y: int, zoom: int) -> str:
    digits = []
    for i in range(zoom, 0, -1):
        digit = 0
        mask = 1 << (i - 1)
        if x & mask:
            digit += 1
        if y & mask:
            digit += 2
        digits.append(str(digit))
    return "".join(digits)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def quadkeys_covering_circle(lat: float, lon: float, radius_m: int) -> list[str]:
    """All zoom-9 quadkeys whose tile the search circle's bounding box touches."""
    lat_delta = math.degrees(radius_m / EARTH_RADIUS_M)
    lon_delta = math.degrees(
        radius_m / (EARTH_RADIUS_M * math.cos(math.radians(lat)))
    )

    corners = [
        (lat + lat_delta, lon - lon_delta),
        (lat + lat_delta, lon + lon_delta),
        (lat - lat_delta, lon - lon_delta),
        (lat - lat_delta, lon + lon_delta),
    ]
    tiles = {deg2tile(clat, clon, ZOOM) for clat, clon in corners}
    xs = [t[0] for t in tiles]
    ys = [t[1] for t in tiles]
    quadkeys = []
    for x in range(min(xs), max(xs) + 1):
        for y in range(min(ys), max(ys) + 1):
            quadkeys.append(tile_to_quadkey(x, y, ZOOM))
    return quadkeys


def download(url: str, dest_path: str, label: str) -> None:
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        print(f"[cache] using cached {label}", file=sys.stderr)
        return
    tmp_path = dest_path + ".part"
    print(f"[download] {label} <- {url}", file=sys.stderr)
    request = urllib.request.Request(
        url, headers={"User-Agent": "count-buildings-msft/1.0"}
    )
    start = time.time()
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
        total = response.headers.get("Content-Length")
        total = int(total) if total else None
        written = 0
        with open(tmp_path, "wb") as f:
            while True:
                chunk = response.read(DOWNLOAD_CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                written += len(chunk)
                if total:
                    pct = written / total * 100
                    print(
                        f"\r[download] {label}: {written / 1e6:.1f}/{total / 1e6:.1f} MB ({pct:.0f}%)",
                        end="",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"\r[download] {label}: {written / 1e6:.1f} MB",
                        end="",
                        file=sys.stderr,
                    )
    print(
        f"  done in {time.time() - start:.1f}s",
        file=sys.stderr,
    )
    os.replace(tmp_path, dest_path)


def load_dataset_links(url: str, cache_dir: str) -> str:
    dest = os.path.join(cache_dir, "dataset-links.csv")
    download(url, dest, "dataset-links.csv")
    return dest


def find_tile_urls(dataset_links_path: str, quadkeys: set[str]) -> list[tuple[str, str]]:
    """Returns list of (location, url) for every row whose QuadKey matches."""
    matches = []
    with open(dataset_links_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["QuadKey"] in quadkeys:
                matches.append((row["Location"], row["Url"]))
    return matches


def cache_path_for_url(cache_dir: str, url: str) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return os.path.join(cache_dir, "tiles", f"{digest}.csv.gz")


def count_buildings_in_tile(
    tile_path: str, lat: float, lon: float, radius_m: int
) -> tuple[int, int]:
    """Returns (matched_count, total_lines_seen) for one tile file."""
    matched = 0
    seen = 0
    with gzip.open(tile_path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            seen += 1
            try:
                feature = json.loads(line)
                geom = feature["geometry"]
                centroid = polygon_centroid(geom)
                if centroid is None:
                    continue
                clat, clon = centroid
                if haversine_m(lat, lon, clat, clon) <= radius_m:
                    matched += 1
            except (json.JSONDecodeError, KeyError, IndexError, ZeroDivisionError):
                continue
            if seen % 200000 == 0:
                print(
                    f"\r[scan] {os.path.basename(tile_path)}: {seen:,} features scanned, {matched:,} matched",
                    end="",
                    file=sys.stderr,
                )
    if seen >= 200000:
        print("", file=sys.stderr)
    return matched, seen


def polygon_centroid(geometry: dict) -> tuple[float, float] | None:
    """Simple average-of-vertices centroid of a Polygon/MultiPolygon's exterior ring(s)."""
    gtype = geometry.get("type")
    if gtype == "Polygon":
        rings = [geometry["coordinates"][0]]
    elif gtype == "MultiPolygon":
        rings = [poly[0] for poly in geometry["coordinates"]]
    else:
        return None

    sum_lon = 0.0
    sum_lat = 0.0
    n = 0
    for ring in rings:
        # last point duplicates the first in a closed ring; skip it
        for lon, lat in ring[:-1]:
            sum_lon += lon
            sum_lat += lat
            n += 1
    if n == 0:
        return None
    return sum_lat / n, sum_lon / n


def run(
    lat: float,
    lon: float,
    radius: int,
    cache_dir: str,
    dataset_links_url: str,
) -> int:
    """Runs one count and returns the total building count."""
    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(os.path.join(cache_dir, "tiles"), exist_ok=True)

    quadkeys = quadkeys_covering_circle(lat, lon, radius)
    print(
        f"Center ({lat}, {lon}), radius {radius} m -> "
        f"{len(quadkeys)} tile(s): {', '.join(quadkeys)}",
        file=sys.stderr,
    )

    try:
        links_path = load_dataset_links(dataset_links_url, cache_dir)
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"error: failed to download dataset-links.csv: {exc}", file=sys.stderr)
        print(
            "The dataset URL may have moved - check the README at "
            "https://github.com/microsoft/GlobalMLBuildingFootprints for the "
            "current link and pass it with --dataset-links-url.",
            file=sys.stderr,
        )
        raise

    tile_urls = find_tile_urls(links_path, set(quadkeys))
    if not tile_urls:
        print("No dataset coverage found for this location.")
        print(f"lat: {lat}")
        print(f"lon: {lon}")
        print(f"radius_m: {radius}")
        print("building_count: 0")
        return 0

    total_matched = 0
    total_seen = 0
    for location, url in tile_urls:
        tile_path = cache_path_for_url(cache_dir, url)
        label = f"{location} ({os.path.basename(url)})"
        try:
            download(url, tile_path, label)
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            print(f"[warn] failed to download {label}: {exc}", file=sys.stderr)
            continue
        matched, seen = count_buildings_in_tile(tile_path, lat, lon, radius)
        total_matched += matched
        total_seen += seen
        print(
            f"[scan] {label}: {matched:,} of {seen:,} buildings within radius",
            file=sys.stderr,
        )

    print(f"lat: {lat}")
    print(f"lon: {lon}")
    print(f"radius_m: {radius}")
    print(f"tiles_used: {len(tile_urls)}")
    print(f"buildings_scanned: {total_seen}")
    print(f"building_count: {total_matched}")
    return total_matched


def ring_index(distance_m: float, ring_bounds=HRS_RING_BOUNDS_M) -> int | None:
    """Index of the ring distance_m falls into (rings are mutually exclusive,
    upper-bound inclusive), or None if beyond the outermost ring."""
    for i, bound in enumerate(ring_bounds):
        if distance_m <= bound:
            return i
    return None


def scan_tile_combined(
    tile_path: str,
    lat: float,
    lon: float,
    radius_m: float,
    ring_bounds=HRS_RING_BOUNDS_M,
) -> tuple[int, list[int], int]:
    """One pass over a tile: returns (count within radius_m, count per HRS
    ring, total features seen). Doing both in one pass avoids scanning a
    multi-hundred-MB tile twice."""
    matched = 0
    ring_counts = [0] * len(ring_bounds)
    seen = 0
    with gzip.open(tile_path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            seen += 1
            try:
                feature = json.loads(line)
                centroid = polygon_centroid(feature["geometry"])
                if centroid is None:
                    continue
                clat, clon = centroid
                d = haversine_m(lat, lon, clat, clon)
                if d <= radius_m:
                    matched += 1
                idx = ring_index(d, ring_bounds)
                if idx is not None:
                    ring_counts[idx] += 1
            except (json.JSONDecodeError, KeyError, IndexError, ZeroDivisionError):
                continue
            if seen % 200000 == 0:
                print(
                    f"\r[scan] {os.path.basename(tile_path)}: {seen:,} features scanned, {matched:,} matched",
                    end="",
                    file=sys.stderr,
                )
    if seen >= 200000:
        print("", file=sys.stderr)
    return matched, ring_counts, seen


def run_combined(
    lat: float,
    lon: float,
    radius_m: float,
    cache_dir: str,
    dataset_links_url: str,
    ring_bounds=HRS_RING_BOUNDS_M,
) -> tuple[int, list[int]]:
    """Like run(), but also buckets every building into HRS Table 5-9's
    distance rings in the same pass - used by the GUI's HRS helper panel."""
    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(os.path.join(cache_dir, "tiles"), exist_ok=True)

    max_extent = max(radius_m, max(ring_bounds))
    quadkeys = quadkeys_covering_circle(lat, lon, max_extent)
    print(
        f"Center ({lat}, {lon}), coverage radius {max_extent} m -> "
        f"{len(quadkeys)} tile(s): {', '.join(quadkeys)}",
        file=sys.stderr,
    )

    try:
        links_path = load_dataset_links(dataset_links_url, cache_dir)
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"error: failed to download dataset-links.csv: {exc}", file=sys.stderr)
        print(
            "The dataset URL may have moved - check the README at "
            "https://github.com/microsoft/GlobalMLBuildingFootprints for the "
            "current link and pass it with --dataset-links-url.",
            file=sys.stderr,
        )
        raise

    tile_urls = find_tile_urls(links_path, set(quadkeys))
    if not tile_urls:
        print("No dataset coverage found for this location.")
        print(f"lat: {lat}")
        print(f"lon: {lon}")
        print("building_count: 0")
        return 0, [0] * len(ring_bounds)

    total_matched = 0
    total_ring_counts = [0] * len(ring_bounds)
    total_seen = 0
    for location, url in tile_urls:
        tile_path = cache_path_for_url(cache_dir, url)
        label = f"{location} ({os.path.basename(url)})"
        try:
            download(url, tile_path, label)
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            print(f"[warn] failed to download {label}: {exc}", file=sys.stderr)
            continue
        matched, ring_counts, seen = scan_tile_combined(
            tile_path, lat, lon, radius_m, ring_bounds
        )
        total_matched += matched
        total_seen += seen
        for i, c in enumerate(ring_counts):
            total_ring_counts[i] += c
        print(
            f"[scan] {label}: {matched:,} of {seen:,} buildings within {radius_m:,.0f} m",
            file=sys.stderr,
        )

    print(f"lat: {lat}")
    print(f"lon: {lon}")
    print(f"radius_m: {radius_m}")
    print(f"tiles_used: {len(tile_urls)}")
    print(f"buildings_scanned: {total_seen}")
    print(f"building_count: {total_matched}")
    for label, count in zip(HRS_RING_LABELS_TH, total_ring_counts):
        print(f"hrs_ring[{label}]: {count}")
    return total_matched, total_ring_counts


def interactive_session() -> None:
    print("=== นับอาคารจาก Microsoft GlobalMLBuildingFootprints ===")
    print("ข้อมูล footprint อาจต้องดาวน์โหลดไทล์ขนาดหลายสิบ-หลายร้อย MB ในการค้นหาครั้งแรกของแต่ละพื้นที่")
    print("พิมพ์ q แล้วกด Enter เพื่อออกจากโปรแกรม\n")
    while True:
        try:
            lat_raw = input("ละติจูด (lat): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if lat_raw.lower() in ("q", "quit", "exit"):
            break
        try:
            lat = float(lat_raw)
        except ValueError:
            print("กรุณากรอกตัวเลข\n")
            continue

        try:
            lon_raw = input("ลองจิจูด (lon): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if lon_raw.lower() in ("q", "quit", "exit"):
            break
        try:
            lon = float(lon_raw)
        except ValueError:
            print("กรุณากรอกตัวเลข\n")
            continue

        try:
            radius_raw = input(f"รัศมี (เมตร) [ค่าเริ่มต้น {DEFAULT_RADIUS_M}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if radius_raw.lower() in ("q", "quit", "exit"):
            break
        try:
            radius = int(radius_raw) if radius_raw else DEFAULT_RADIUS_M
        except ValueError:
            print("รัศมีต้องเป็นตัวเลข\n")
            continue

        print()
        try:
            run(lat, lon, radius, DEFAULT_CACHE_DIR, DEFAULT_DATASET_LINKS_URL)
        except Exception as exc:  # noqa: BLE001 - keep the window open on any failure
            print(f"เกิดข้อผิดพลาด: {exc}")
        print("\n" + "-" * 60 + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Count buildings within a radius of a coordinate using Microsoft's "
            "GlobalMLBuildingFootprints dataset."
        )
    )
    parser.add_argument("lat", type=float, help="Latitude of the center point")
    parser.add_argument("lon", type=float, help="Longitude of the center point")
    parser.add_argument(
        "--radius",
        type=int,
        default=DEFAULT_RADIUS_M,
        help=f"Search radius in meters (default: {DEFAULT_RADIUS_M})",
    )
    parser.add_argument(
        "--cache-dir",
        default=DEFAULT_CACHE_DIR,
        help=f"Where to cache dataset-links.csv and downloaded tiles (default: ./{DEFAULT_CACHE_DIR})",
    )
    parser.add_argument(
        "--dataset-links-url",
        default=DEFAULT_DATASET_LINKS_URL,
        help=(
            "Override the dataset-links.csv URL if Microsoft has moved it "
            "(check https://github.com/microsoft/GlobalMLBuildingFootprints for the current link)."
        ),
    )
    return parser.parse_args()


def main() -> None:
    # Windows consoles opened by double-clicking a packaged .exe can default
    # to a legacy codepage that can't render Thai text; force UTF-8 output
    # so prompts and results never crash the console.
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    if len(sys.argv) == 1:
        # No arguments: most likely launched by double-clicking the packaged
        # executable rather than from a terminal, so run interactively and
        # keep the console open instead of exiting after an argparse error.
        try:
            interactive_session()
        except Exception as exc:  # noqa: BLE001 - always show the error, never vanish
            print(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {exc}")
        try:
            input("\nกด Enter เพื่อปิดหน้าต่าง...")
        except (EOFError, KeyboardInterrupt):
            pass
        return

    args = parse_args()
    run(args.lat, args.lon, args.radius, args.cache_dir, args.dataset_links_url)


if __name__ == "__main__":
    main()
